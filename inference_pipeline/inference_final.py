import cv2
import os
import numpy as np
from dataclasses import dataclass, field
from collections import deque
from typing import List, Tuple, Dict
import json
from ultralytics import YOLO
import matplotlib.pyplot as plt
import torch
import argparse

FPS = 30 # fps of the video we are using
PATIENCE_FRAMES = 60  # Frames to wait before closing a lost track

def crop_and_resize(input_img, target_width = 576, target_height=896):
    img = input_img.copy()
    h, w, _ = img.shape

    if h == target_height and w == target_width:
        return img
    target_aspect = target_width / target_height

    new_h = int(w / target_aspect)

    # how much im cutting off
    crop_total = h - new_h
    # make sure we arent going to negatives by finding a safe crop total, but still retain the desired height
    crop_top = crop_total // 2 - 100
    crop_bottom = crop_total - crop_top + 100
    # if crop_top is negative, set it to 0 and adjust crop_bottom accordingly
    if crop_top < 0:
        crop_top = 0
        crop_bottom = crop_total
    y1 = crop_top
    y2 = h - crop_bottom
    x1 = 0
    x2 = w

    # get target aspect ratio
    # determine new height and width of entire image BEFORE RESIZING
    # find dimensions to make cut - I only cut off the top and the bottom of the image. This requires some domain knowledge because I know the game occurs in the middle of the screen, so I don't need top and bottom. 
    # once you find the dimensions you need to cut, then perform the crop
    cropped = img[y1:y2, x1:x2]
    # resize
    resized = cv2.resize(cropped, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return resized

def preprocess_video(input_vid_path, output_vid_path, target_width = 576, target_height=896):
    # open the video here
    cap = cv2.VideoCapture(input_vid_path)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    # set the ouput - i have a 30 fps video, and i know what i want the dimensions to be, so i can set those here.
    out = cv2.VideoWriter(output_vid_path, fourcc, 30.0, (target_width, target_height))

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        processed_frame = crop_and_resize(frame, target_width, target_height)
        out.write(processed_frame)

    cap.release()
    out.release()

def process_frame(frame_path, model):
    img = cv2.imread(frame_path)
    results = model.predict(
        source=img,
        save=False,
        imgsz=896,
        conf=0.5
    )
    return results

def process_video(video_path, model):
    _repo_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    _yolo_out = os.path.join(_repo_root, "outputs", "yolo_runs")
    results = model.track(
    source=video_path,
    save=True,
    imgsz=896,
    conf=0.5,
    project=_yolo_out,
    name="bbox_overlay",
    exist_ok=True,
    tracker="bytetrack.yaml",
    stream=True,
    persist=True
    )
    return results

@dataclass
class TrackedObject:
    """
    Lean object to store track ID, class, and raw coordinate history.
    """
    track_id: int
    class_id: int
    start_frame: int
    
    positions: List[Tuple[float, float]] = field(default_factory=list)
    last_seen_frame: int = 0
    
    def update(self, position: Tuple[float, float], frame_id: int):
        self.positions.append(position)
        self.last_seen_frame = frame_id

    @property
    def duration_seconds(self) -> float:
        return (self.last_seen_frame - self.start_frame) / FPS

    @property
    def start_position(self) -> Tuple[float, float]:
        return self.positions[0] if self.positions else (0, 0)

    @property
    def end_position(self) -> Tuple[float, float]:
        return self.positions[-1] if self.positions else (0, 0)

    def to_dict(self):
        """Convert to standard Python types for JSON export."""
        return {
            "track_id": int(self.track_id),
            "class_id": int(self.class_id),
            "start_frame": int(self.start_frame),
            "end_frame": int(self.last_seen_frame),
            "duration_seconds": float(self.duration_seconds),
            "positions": [[float(x), float(y)] for x, y in self.positions]
        }
    

class GameTracker:
    def __init__(self, patience_threshold=30):
        self.active_tracks: Dict[int, TrackedObject] = {}
        self.lost_counters: Dict[int, int] = {}
        self.completed_tracks: List[TrackedObject] = []
        self.patience = patience_threshold
    
    def update(self, tracks, frame_id: int):
        current_frame_track_ids = set()

        # 1. Update/Create Active Tracks
        for track in tracks:
            x1, y1, x2, y2 = track[0:4]
            track_id = int(track[6])
            class_id = int(track[5])
            
            centroid = ((x1 + x2) / 2, (y1 + y2) / 2)
            current_frame_track_ids.add(track_id)

            if track_id in self.active_tracks:
                self.active_tracks[track_id].update(centroid, frame_id)
                # Object found, reset lost counter
                if track_id in self.lost_counters:
                    del self.lost_counters[track_id]
            else:
                new_obj = TrackedObject(track_id, class_id, frame_id)
                new_obj.update(centroid, frame_id)
                self.active_tracks[track_id] = new_obj
        
        # 2. Handle Lost Tracks (Patience Buffer)
        active_ids = list(self.active_tracks.keys())
        for tid in active_ids:
            if tid not in current_frame_track_ids:
                self.lost_counters[tid] = self.lost_counters.get(tid, 0) + 1
                
                if self.lost_counters[tid] > self.patience:
                    finished_obj = self.active_tracks.pop(tid)
                    self.completed_tracks.append(finished_obj)
                    del self.lost_counters[tid]

    def finalize(self):
        """Push all remaining active tracks to completed."""
        for obj in self.active_tracks.values():
            self.completed_tracks.append(obj)
        self.active_tracks.clear()
        self.lost_counters.clear()

    def save_to_json(self, filename="game_tracking_data.json"):
        """Export all completed tracking data."""
        data = {
            "metadata": {
                "total_tracks": len(self.completed_tracks),
                "patience_setting": self.patience
            },
            "tracks": [t.to_dict() for t in self.completed_tracks]
        }
        with open(filename, 'w') as f:
            json.dump(data, f, indent=4)
        print(f"Data successfully saved to {filename}")


def process_tracks(tracker_results):
    tracker = GameTracker(patience_threshold=PATIENCE_FRAMES)
    for frame_idx, result in enumerate(tracker_results):
        # SAFETY CHECK: If there are no detections or no track IDs, skip this frame
        if result.boxes is None or result.boxes.id is None:
            # We still need to update the tracker to age out "lost" tracks
            tracker.update([], frame_id=frame_idx) 
            continue

        xyxy = result.boxes.xyxy.cpu().numpy()
        conf = result.boxes.conf.cpu().numpy()
        cls = result.boxes.cls.cpu().numpy()
        ids = result.boxes.id.cpu().numpy()

        detections = []
        for (box, track_id, score, class_id) in zip(xyxy, ids, conf, cls):
            detections.append([box[0], box[1], box[2], box[3], score, class_id, track_id])
        
        tracker.update(detections, frame_id=frame_idx)
    
    tracker.finalize()
    return tracker



def print_summary(tracker_obj, output_json="hog_2_6_start_tracks.json"):
    print(f"{'ID':<5} {'Class':<10} {'Duration (s)':<15} {'Start Pos':<20} {'End Pos':<20} {'Avg Vel (px/f)'}")
    print("-" * 90)
    for obj in tracker_obj.completed_tracks:
        # Calculate global velocity here instead of live
        if len(obj.positions) > 1:
            start_arr = np.array(obj.start_position)
            end_arr = np.array(obj.end_position)
            total_disp = np.linalg.norm(end_arr - start_arr)
            total_frames = obj.last_seen_frame - obj.start_frame
            global_avg_vel = total_disp / total_frames if total_frames > 0 else 0
        else:
            global_avg_vel = 0
            
        print(f"{obj.track_id:<5} {obj.class_id:<10} {obj.duration_seconds:<15.2f} "
              f"{str(tuple(map(int, obj.start_position))):<20} "
              f"{str(tuple(map(int, obj.end_position))):<20} "
              f"{global_avg_vel:.2f}")
        
        tracker_obj.save_to_json(output_json)  # Save after printing summary
        
def main():
    # argparser
    parser = argparse.ArgumentParser(description="Preprocess video, feed into YOLO26, collect tracked objects")
    parser.add_argument('input_video', type=str, help="path to input vid")
    parser.add_argument('output_video', type=str, help="path to save preprocessed vid")
    parser.add_argument('output_json_path', type=str, help="path to save output json")
    parser.add_argument('--model_path', type=str, default="clash_yolo_4_13.pt", help="path to YOLO model")
    parser.add_argument('--input_h', type=int, default=896, help="height of input video")
    parser.add_argument('--input_w', type=int, default=576, help="width of input video")
    parser.parse_args()

    args = parser.parse_args()

    input_path = args.input_video
    output_path = args.output_video
    input_h = args.input_h
    input_w = args.input_w

    preprocess_video(input_path, output_path, target_width=input_w, target_height=input_h)
    model = YOLO(args.model_path)

    tracker = GameTracker(patience_threshold=PATIENCE_FRAMES)
    results = process_video(output_path, model)
    tracker = process_tracks(results)
    print_summary(tracker, output_json=args.output_json_path)


if __name__ == "__main__":
    main()

