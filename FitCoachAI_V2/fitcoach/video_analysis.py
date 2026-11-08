
"""Optional short-video pose overlay for FitCoach AI.

This module visualizes pose landmarks only. It does NOT diagnose injuries,
certify technique safety, or score exercise quality.
"""
from pathlib import Path

MAX_SECONDS = 20
MAX_WIDTH = 720

def analyze_video(input_path: str, output_path: str) -> dict:
    import cv2
    try:
        import mediapipe as mp
    except Exception as exc:
        raise RuntimeError(
            "بسته‌های تحلیل ویدئو نصب نیستند. requirements-video.txt را نصب کن."
        ) from exc

    cap = cv2.VideoCapture(str(input_path))
    if not cap.isOpened():
        raise RuntimeError("ویدئو قابل خواندن نیست.")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = frame_count / fps if fps > 0 else 0

    if duration <= 0 or duration > MAX_SECONDS:
        cap.release()
        raise ValueError(f"مدت ویدئو باید بین ۱ تا {MAX_SECONDS} ثانیه باشد.")
    if width < 160 or height < 160:
        cap.release()
        raise ValueError("کیفیت یا ابعاد ویدئو برای تحلیل کافی نیست.")

    scale = min(1.0, MAX_WIDTH / max(width, height))
    out_w, out_h = max(2, int(width * scale)), max(2, int(height * scale))
    if out_w % 2: out_w -= 1
    if out_h % 2: out_h -= 1

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, min(max(fps, 12), 30), (out_w, out_h))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("ساخت فایل ویدئوی خروجی ناموفق بود.")

    mp_pose = mp.solutions.pose
    mp_draw = mp.solutions.drawing_utils
    processed = 0
    detected = 0
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,
        enable_segmentation=False,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = cv2.resize(frame, (out_w, out_h))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = pose.process(rgb)
            if result.pose_landmarks:
                detected += 1
                mp_draw.draw_landmarks(
                    frame,
                    result.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS,
                    landmark_drawing_spec=mp_draw.DrawingSpec(
                        color=(80, 230, 120), thickness=2, circle_radius=2
                    ),
                    connection_drawing_spec=mp_draw.DrawingSpec(
                        color=(40, 180, 255), thickness=2
                    ),
                )
            cv2.putText(
                frame, "FitCoach AI | Pose landmarks",
                (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.58,
                (255, 255, 255), 2, cv2.LINE_AA
            )
            writer.write(frame)
            processed += 1
    finally:
        pose.close()
        cap.release()
        writer.release()

    if processed == 0:
        raise RuntimeError("هیچ فریمی از ویدئو خوانده نشد.")
    ratio = detected / processed
    return {
        "frames": processed,
        "pose_frames": detected,
        "pose_detection_ratio": round(ratio, 3),
        "duration": round(duration, 1),
        "width": out_w,
        "height": out_h,
    }
