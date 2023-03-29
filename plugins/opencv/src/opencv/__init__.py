from __future__ import annotations

from typing import Any, List, Tuple

import cv2
import imutils
import numpy as np

from detect import DetectPlugin

import scrypted_sdk
from scrypted_sdk.types import (ObjectDetectionGeneratorSession,
                                ObjectDetectionResult,
                                ObjectsDetected, Setting, VideoFrame)


class OpenCVDetectionSession:
    def __init__(self) -> None:
        self.cap: cv2.VideoCapture = None
        self.previous_frame: Any = None
        self.curFrame = None
        self.frameDelta = None
        self.dilated = None
        self.thresh = None
        self.gray = None
        self.gstsample = None


defaultThreshold = 25
defaultArea = 200
defaultInterval = 250
defaultBlur = 5

class OpenCVPlugin(DetectPlugin):
    def __init__(self, nativeId: str | None = None):
        super().__init__(nativeId=nativeId)
        self.color2Gray = None
        self.pixelFormat = "I420"
        self.pixelFormatChannelCount = 1

        if True:
            self.retainAspectRatio = False
            self.color2Gray = None
            self.pixelFormat = "I420"
            self.pixelFormatChannelCount = 1
        else:
            self.retainAspectRatio = True
            self.color2Gray = cv2.COLOR_BGRA2GRAY
            self.pixelFormat = "BGRA"
            self.pixelFormatChannelCount = 4


    def getClasses(self) -> list[str]:
        return ['motion']

    def getModelSettings(self, settings: Any = None) -> list[Setting]:
        settings = [
            {
                'title': "Motion Area",
                'description': "The area size required to trigger motion. Higher values (larger areas) are less sensitive. Setting this to 0 will output all matches into the console.",
                'value': defaultArea,
                'key': 'area',
                'placeholder': defaultArea,
                'type': 'number',
            },
            {
                'title': "Motion Threshold",
                'description': "The threshold required to consider a pixel changed. Higher values (larger changes) are less sensitive.",
                'value': defaultThreshold,
                'key': 'threshold',
                'placeholder': defaultThreshold,
                'type': 'number',
            },
            {
                'title': "Blur Radius",
                'description': "The radius of the blur applied to denoise small amounts of motion.",
                'value': defaultBlur,
                'key': 'blur',
                'placeholder': defaultBlur,
                'type': 'number',
            },
            {
                'title': "Frame Analysis Interval",
                'description': "The number of milliseconds to wait between motion analysis.",
                'value': defaultInterval,
                'key': 'interval',
                'placeholder': defaultInterval,
                'type': 'number',
            },
        ]

        return settings

    def get_pixel_format(self):
        return self.pixelFormat
    
    def get_input_format(self) -> str:
        return 'gray'

    def parse_settings(self, settings: Any):
        area = defaultArea
        threshold = defaultThreshold
        interval = defaultInterval
        blur = defaultBlur
        if settings:
            area = float(settings.get('area', area))
            threshold = int(settings.get('threshold', threshold))
            interval = float(settings.get('interval', interval))
            blur = int(settings.get('blur', blur))
        return area, threshold, interval, blur

    def detect(self, frame, settings: Any, detection_session: OpenCVDetectionSession, src_size, convert_to_src_size) -> ObjectsDetected:
        area, threshold, interval, blur = self.parse_settings(settings)

        # see get_detection_input_size on undocumented size requirements for GRAY8
        if self.color2Gray != None:
            detection_session.gray = cv2.cvtColor(
                frame, self.color2Gray, dst=detection_session.gray)
            gray = detection_session.gray
        else:
            gray = frame
        detection_session.curFrame = cv2.GaussianBlur(
            gray, (blur, blur), 0, dst=detection_session.curFrame)

        detections: List[ObjectDetectionResult] = []
        detection_result: ObjectsDetected = {}
        detection_result['detections'] = detections
        detection_result['inputDimensions'] = src_size

        if detection_session.previous_frame is None:
            detection_session.previous_frame = detection_session.curFrame
            detection_session.curFrame = None
            return detection_result

        detection_session.frameDelta = cv2.absdiff(
            detection_session.previous_frame, detection_session.curFrame, dst=detection_session.frameDelta)
        tmp = detection_session.curFrame
        detection_session.curFrame = detection_session.previous_frame
        detection_session.previous_frame = tmp

        _, detection_session.thresh = cv2.threshold(
            detection_session.frameDelta, threshold, 255, cv2.THRESH_BINARY, dst=detection_session.thresh)
        detection_session.dilated = cv2.dilate(
            detection_session.thresh, None, iterations=2, dst=detection_session.dilated)
        fcontours = cv2.findContours(
            detection_session.dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = imutils.grab_contours(fcontours)


        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            # if w * h != contour_area:
            #     print("mismatch w/h", contour_area - w * h)

            x2, y2 = convert_to_src_size((x + w, y + h))
            x, y = convert_to_src_size((x, y))
            w = x2 - x + 1
            h = y2 - y + 1

            contour_area = w * h

            if not area or contour_area > area:
                detection: ObjectDetectionResult = {}
                detection['boundingBox'] = (x, y, w, h)
                detection['className'] = 'motion'
                detection['score'] = 1 if area else contour_area
                detections.append(detection)

        return detection_result
    
    def get_input_details(self) -> Tuple[int, int, int]:
        return (300, 300, 1)

    def get_detection_input_size(self, src_size):
        # The initial implementation of this plugin used BGRA
        # because it seemed impossible to pull the Y frame out of I420 without corruption.
        # This is because while 318x174 is aspect ratio correct,
        # it seems to cause strange issues with stride and the image is skewed.
        # By using 300x300, this seems to avoid some undocumented minimum size
        # reqiurement in gst-videoscale or opencv. Unclear which.

        # This is the same input size as tensorflow-lite. Allows for better pipelining.
        if not self.retainAspectRatio:
            return (300, 300)

        width, height = src_size
        if (width > height):
            if (width > 318):
                height = height / width * 318
                width = 318
        else:
            if (height > 318):
                width = width / height * 318
                height = 318

        width = int(np.floor(width / 6) * 6)
        height = int(np.floor(height / 6) * 6)

        return width, height

    def end_session(self, detection_session: OpenCVDetectionSession):
        if detection_session and detection_session.cap:
            detection_session.cap.release()
            detection_session.cap = None
        return super().end_session(detection_session)

    async def generateObjectDetections(self, videoFrames: Any, session: ObjectDetectionGeneratorSession = None) -> Any:
        try:
            ds = OpenCVDetectionSession()
            videoFrames = await scrypted_sdk.sdk.connectRPCObject(videoFrames)
            async for videoFrame in videoFrames:
               detected = await self.run_detection_videoframe(videoFrame, session and session.get('settings'), ds)
               yield {
                   '__json_copy_serialize_children': True,
                   'detected': detected,
                   'videoFrame': videoFrame,
               }
        finally:
            try:
                await videoFrames.aclose()
            except:
                pass

    async def run_detection_videoframe(self, videoFrame: VideoFrame, settings: Any, detection_session: OpenCVDetectionSession) -> ObjectsDetected:
        width = videoFrame.width
        height = videoFrame.height

        aspectRatio = width / height
        
        # dont bother resizing if its already fairly small
        if width <= 640 and height < 640:
            scale = 1
            resize = None
        else:
            if aspectRatio > 1:
                scale = height / 300
                height = 300
                width = int(300 * aspectRatio)
            else:
                width = 300
                height = int(300 / aspectRatio)
                scale = width / 300
            resize = {
                'width': width,
                'height': height,
            }

        buffer = await videoFrame.toBuffer({
            'resize': resize,
        })

        def convert_to_src_size(point):
            return point[0] * scale, point[1] * scale
        mat = np.ndarray((height, width, self.pixelFormatChannelCount), buffer=buffer, dtype=np.uint8)
        detections = self.detect(mat, settings, detection_session,  (width, height), convert_to_src_size)
        return detections
