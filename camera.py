import cv2
import time
import os
import numpy as np
import mediapipe as mp
import pygame
from ultralytics import YOLO
from flask import current_app
from database import db, ActivityLog

class IntelligentCamera:
    def __init__(self, app):
        self.app = app
        self.cap = None  # Hardware initially OFF
        
        # --- STATE ---
        self.is_running = False 
        self.siren_enabled = True
        self.siren_active = False
        
        # --- PATHS ---
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.model_path = os.path.join(base_dir, 'models', 'weapon.pt')
        self.siren_path = os.path.join(base_dir, 'static', 'siren.mp3')

        # --- LOAD MODEL ---
        if os.path.exists(self.model_path):
            self.model = YOLO(self.model_path)
            print("✅ AI Model Loaded")
        else:
            self.model = None

        # --- LOAD MEDIAPIPE ---
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(min_detection_confidence=0.5)

        # --- AUDIO ---
        pygame.mixer.init()
        self.last_log_time = 0

    def start_camera(self):
        """Turn ON Hardware with Warm-Up"""
        if not self.is_running:
            # 1. Force DirectShow (Best for Windows)
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            
            # 2. Check if valid
            if not self.cap.isOpened():
                self.cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)

            # 3. THE FIX: WARM UP CAMERA (Clear Black Buffer)
            if self.cap.isOpened():
                for _ in range(10):
                    self.cap.read()
            
            self.is_running = True
            print("📷 Camera Warmed Up & Started")

    def stop_camera(self):
        """Turn OFF Hardware"""
        self.is_running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        self.stop_siren()
        print("📷 Camera Stopped")

    def stop_siren(self):
        if self.siren_active:
            pygame.mixer.music.stop()
            self.siren_active = False

    def play_siren(self):
        if self.siren_enabled and not self.siren_active:
            if os.path.exists(self.siren_path):
                pygame.mixer.music.load(self.siren_path)
                pygame.mixer.music.play(-1)
                self.siren_active = True

    def log_db(self, event, details, severity):
        if time.time() - self.last_log_time > 4.0:
            self.last_log_time = time.time()
            with self.app.app_context():
                try:
                    db.session.add(ActivityLog(event_type=event, details=details, severity=severity))
                    db.session.commit()
                except:
                    pass

    def get_frame(self):
        # 1. STANDBY MODE
        if not self.is_running or self.cap is None:
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank, "SYSTEM STANDBY", (180, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.putText(blank, "Press 'Start Activation'", (190, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            ret, jpeg = cv2.imencode('.jpg', blank)
            return jpeg.tobytes()

        # 2. ACTIVE MODE
        success, frame = self.cap.read()
        
        # --- SELF-HEALING: If frame is black/empty, restart ---
        if not success or frame is None:
            print("⚠️ Frame Lost - Restarting Hardware...")
            self.cap.release()
            self.start_camera() # Restart logic
            
            # Show temporary loading screen
            err = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(err, "RELOADING...", (220, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            ret, jpeg = cv2.imencode('.jpg', err)
            return jpeg.tobytes()

        frame = cv2.flip(frame, 1)
        threat_detected = False
        status_text = "SYSTEM SECURE"
        status_color = (0, 255, 0)

        # --- A. WEAPON DETECTION ---
        if self.model:
            results = self.model(frame, verbose=False, conf=0.30) 
            ALLOWED_KEYWORDS = ['gun', 'pistol', 'rifle', 'handgun', 'knife', 'dagger', 'grenade', 'weapon', 'sword']

            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    label = self.model.names[cls_id].lower()
                    conf = float(box.conf[0])
                    
                    is_weapon = any(k in label for k in ALLOWED_KEYWORDS)
                    if is_weapon:
                        if label not in ['person', 'face']:
                            threat_detected = True
                            status_text = f"THREAT: {label.upper()}"
                            status_color = (0, 0, 255)
                            self.log_db("WEAPON DETECTED", f"Obj: {label}", "CRITICAL")
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            cv2.putText(frame, f"{label} {int(conf*100)}%", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # --- B. POSE DETECTION ---
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self.pose.process(rgb)
        if res.pose_landmarks:
            mp.solutions.drawing_utils.draw_landmarks(frame, res.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)
            lm = res.pose_landmarks.landmark
            nose = lm[self.mp_pose.PoseLandmark.NOSE]
            hip = lm[self.mp_pose.PoseLandmark.LEFT_HIP]
            wrist_l = lm[self.mp_pose.PoseLandmark.LEFT_WRIST]
            eye_l = lm[self.mp_pose.PoseLandmark.LEFT_EYE]

            if abs(nose.y - hip.y) < 0.2:
                if not threat_detected:
                    threat_detected = True
                    status_text = "FALL DETECTED"
                    status_color = (0, 165, 255)
                    self.log_db("FALL DETECTED", "Person Down", "HIGH")
            elif wrist_l.y < eye_l.y:
                if not threat_detected:
                    threat_detected = True
                    status_text = "HANDS RAISED"
                    status_color = (0, 255, 255)
                    self.log_db("SUSPICIOUS", "Hands Up", "MEDIUM")

        # --- C. ALERTS ---
        if threat_detected:
            self.play_siren()
        else:
            self.stop_siren()

        cv2.rectangle(frame, (0, 0), (640, 50), status_color, -1)
        cv2.putText(frame, f"INTELLISURVEIL: {status_text}", (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        ret, jpeg = cv2.imencode('.jpg', frame)
        return jpeg.tobytes()