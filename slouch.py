import cv2
import sys
import statistics
import time
from PyQt5 import Qt
import PyQt5.QtCore as QtCore
from PyQt5.QtWidgets import QApplication, QWidget, QDesktopWidget, QMainWindow, QSystemTrayIcon, QMenu, QMessageBox, QAction
from PyQt5.QtGui import QIcon, QPainter, QColor, QFont, QImage, QPixmap
import sys
import threading
from PyQt5 import uic
import timeout_decorator

DEBUG = False

# Path to face cascade
cascPath = "./facecascade.xml"
faceCascade = cv2.CascadeClassifier(cascPath)

# Start webcam capture
video_capture = cv2.VideoCapture('http://10.0.0.14:4747/mjpegfeed')
camera_working = True


@timeout_decorator.timeout(0.5, use_signals=False)
def test_cam(cap):
    if cap is None or not cap.isOpened():
        return False
    r, f = cap.read()
    return True


try:
    camera_working = test_cam(video_capture)
except timeout_decorator.timeout_decorator.TimeoutError:
    camera_working = False

# Globals:
calibration = []
calibrated = -1

is_face = False
at_computer = True
is_leaning = False
is_slouching = False
current_break = False
since_last_sighting = 0

BETWEEN_BREAKS = 60 * 15  # 15 minutes
BREAK_LENGTH = 30  # 2 minutes

LEAN_SCALE = 1.3


def dispHelp():
    QMessageBox.about(ex, 'About AntiSlouch',
                      "AntiSlouch is a program that will help you control your posture while using a computer!\n" +
                      "Whenever you slouch in your chair, AntiSlouch will help you correct yourself.\n" +
                      "Programmed by Otto Sapora during CodeDay 2018")


class SystemTrayIcon(QSystemTrayIcon):

    def __init__(self, icon, parent=None):
        super(SystemTrayIcon, self).__init__(icon, parent)
        menu = QMenu(parent)
        self.activated.connect(exitApp)
        helpAction = menu.addAction("About")
        exitAction = menu.addAction("Exit")
        exitAction.triggered.connect(exitApp)
        helpAction.triggered.connect(dispHelp)
        self.setContextMenu(menu)


class Dimmer(QWidget):

    def __init__(self, win):
        super().__init__()
        self.par = win
        self.title = ''
        self.left = 10
        self.top = 10
        self.width = 640
        self.height = 480
        self.initUI()

    def initUI(self):
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint)
        self.setWindowOpacity(0.7)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setWindowTitle(self.title)
        self.setGeometry(self.left, self.top, self.width, self.height)

    def closeEvent(self, event):
        # Don't
        event.ignore()

    def activate(self):
        self.showFullScreen()
        time.sleep(0.1)
        self.par.activateWindow()


class App(QMainWindow):

    def __init__(self):
        super().__init__()
        # Load QT UI file
        uic.loadUi('slouch.ui', self)
        # Init user interface
        self.initUI()

    def closeEvent(self, event):
        # Clean up
        video_capture.release()
        sys.exit(0)

    # Paints the processed image on top
    def paint_picture(self, image):
        # Image properties
        height, width, byteValue = image.shape
        byteValue = byteValue * width
        # Switch red and blue
        cv2.cvtColor(image, cv2.COLOR_BGR2RGB, image)
        # Convert CV image to QImage
        mQImage = QImage(image, width, height, byteValue, QImage.Format_RGB888)
        # Draw QImage on label
        self.picture.setPixmap(QPixmap(mQImage))

    def initUI(self):
        # Init system tray icon
        self.tray_icon = SystemTrayIcon(QIcon('slouching.png'), self)
        self.tray_icon.show()

        # Center in screen
        qtRectangle = self.frameGeometry()
        centerPoint = QDesktopWidget().availableGeometry().center()
        qtRectangle.moveCenter(centerPoint)
        self.move(qtRectangle.topLeft())

        # Disable resizing
        self.setFixedSize(self.size())

        # Hide alert labels
        self.alertTitle.hide()
        self.alertPicture.hide()
        self.alertMessage.hide()

        # Events
        self.calibrateButton.clicked.connect(calibration_button_pressed)

        # Hide debug elements
        if not DEBUG:
            self.slouchPercent.hide()

        # Dimmer

        self.dim = Dimmer(self)

        self.show()


def calibration_button_pressed():
    global calibrated
    # -1 : Not started, 0 : Calibrating, 1 : Done calibrating
    calibrated = 0
    ex.calibrateLabel.setText("Calibrating...\nSit up straight!")


def secs_to_pretty(seconds):
    seconds = int(seconds)
    mins = int(seconds / 60)
    seconds -= 60*mins
    return str(mins).zfill(2) + ":" + str(seconds).zfill(2)


def calibration_mean(data):
    # Calculate mean of each tuple value
    meanTop = sum(t for t, h in data)/len(data)
    meanHeight = sum(h for t, h in data)/len(data)
    return (meanTop, meanHeight)


def update_lean():
    global is_leaning
    global systemtray_icon
    print("[DEBUG] Leaning now " + str(is_leaning))
    if (is_leaning):
        # systemtray_icon.showMessage('AntiSlouch', "You're leaning into your computer.")
        notify("You're slouching. Sit up!")
    else:
        ex.hide()
        ex.dim.hide()


def update_slouch():
    global is_slouching
    global systemtray_icon
    print("[DEBUG] Slouching now " + str(is_slouching))
    if (is_slouching):
        # systemtray_icon.showMessage('AntiSlouch', "You're slouching. Sit up!")
        notify("You're slouching. Sit up!")
    else:
        ex.hide()
        ex.dim.hide()


def notify(text, redo=True):
    # ex.activateWindow()
    print("[DEBUG] Notify: " + text)
    if redo:
        ex.show()
        ex.dim.activate()
    ex.alertTitle.show()
    ex.alertPicture.show()
    ex.alertMessage.setText(text)
    ex.alertMessage.show()


def main():
    global at_computer
    global calibrated
    global calibration
    global since_last_sighting
    global is_leaning
    global is_slouching
    while True:
        # Capture frame-by-frame
        ret, frame = video_capture.read()
        # Grayscale the image
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Detect faces
        faces = faceCascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
            flags=cv2.CASCADE_SCALE_IMAGE
        )
        # If there are faces in the image
        #print(since_last_sighting)
        if(len(faces) > 0):
            is_face = True
            # Reset the "away" counter
            if (since_last_sighting > 0):
                since_last_sighting = -20
            elif (since_last_sighting > -11):
                since_last_sighting -= 2

            # Find the largest face
            targetFace = max(faces, key=lambda x: x[2])

            (x, y, w, h) = targetFace

            # Draw a green rectangle around it
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            # If calibration has been started or is done
            if (calibrated != -1):
                # If calibrating, add calibration value
                if (calibrated == 0):
                    # Top of head + height / 2 = middle of head
                    calibration.append((y + h / 2, h))
                    # Increment progress bar
                    ex.progressBar.setValue(len(calibration))

                # Stop calibrating after 20 values
                if (len(calibration) > 20):
                    # Mark done, get mean
                    calibrated = 1
                    calibration = calibration_mean(calibration)
                    # Hide controls
                    ex.calibrateLabel.hide()
                    ex.progressBar.hide()
                    ex.calibrateIsFace.hide()
                    ex.calibrateButton.hide()
                    ex.picture.hide()
                    ex.calibrateButton.setText("Calibrated")

                    # Always on top, Remove window frame
                    ex.setWindowFlags(QtCore.Qt.Window |
                                      QtCore.Qt.CustomizeWindowHint |
                                      QtCore.Qt.WindowStaysOnTopHint |
                                      QtCore.Qt.FramelessWindowHint)

                    # Hide window
                    ex.hide()

                # If calibrated
                if(calibrated == 1 and not current_break):
                    # t: middle of head, h: height of head
                    (ct, ch) = calibration
                    (rt, rh) = (y + h / 2, h)

                    #cv2.line(frame, (0, 10), (frame.shape[2], 10), (255, 0, 0), 2)

                    was_slouching = is_slouching

                    # If middle of head is below bottom of calibration head
                    if (ct + ch / 3 < rt):
                        is_slouching = True
                    else:
                        is_slouching = False

                    if (was_slouching != is_slouching):
                        update_slouch()
                    # If head size is more than LEAN_SCALE times calibration height
                    was_leaning = is_leaning
                    #print(ct+ch/3, rt)
                    if (ch * LEAN_SCALE < rh):
                        is_leaning = True
                    else:
                        is_leaning = False
                    if (was_leaning != is_leaning and not is_slouching):
                        update_lean()
                    if DEBUG:
                        ex.slouchPercent.setText(str(int((1 - (ct/rt)) * 200)) + f"% slouch\n" +
                                                 str(int((rh - ch)*5/2)) + f"% lean")
        else:
            # Increment away counter if no faces
            since_last_sighting += 1

            is_face = False

        # If calibrated
        if (calibrated == 1):
            # Set if at computer
            if (since_last_sighting > 5 and at_computer):
                print("[DEBUG] No longer at computer")
                at_computer = False
            elif (since_last_sighting < -5 and not at_computer):
                print("[DEBUG] Now at computer")
                at_computer = True
        elif ('ex' in globals()):
            ex.calibrateIsFace.setStyleSheet(
                'color: ' + ('green' if is_face else 'red'))
            ex.calibrateIsFace.setText(('✔' if is_face else '❌') + " Face")

        # If the app is open and we're calibrating, paint the picture
        if('ex' in globals() and calibrated != 1):
            ex.paint_picture(frame)
        if DEBUG:
            cv2.imshow('Slouch', frame)


def take_break():
    global current_break
    # Wait until calibrated
    while (calibrated != 1):
        pass
    if DEBUG:
        time.sleep(15)
    else:
        time.sleep(15)
        # time.sleep(BETWEEN_BREAKS)
    while True:
        # Log the start
        starttime = time.time()
        current_break = True
        # Use the running photo
        ex.alertPicture.setPixmap(QPixmap('break.png'))

        # Wait until they leave
        while at_computer:
            notify("It's time to take a 2-minute break!\nLeave the computer now.")
            time.sleep(0.5)
        # Start the break
        startbreak = time.time()
        while True:
            time.sleep(1)
            # String to display
            notif = secs_to_pretty(
                BREAK_LENGTH - (time.time()-startbreak)) + " left"
            if at_computer:
                notif += " (paused)\nIt's break time!"
                startbreak += 1
            # Notify
            notify(notif, False)
            # Break break if break is broken
            if (int(time.time()-startbreak) > BREAK_LENGTH):
                break
        print("Break finished!")
        ex.alertPicture.setPixmap(QPixmap('slouching.png'))
        # Hide window
        ex.hide()
        ex.dim.hide()
        current_break = False
        # Wait until next break
        time.sleep(BETWEEN_BREAKS -
                   ((time.time() - starttime) % BETWEEN_BREAKS))


# Spin up a few 'threads
t2 = threading.Thread(target=take_break)
t2.daemon = True
t2.start()
t = threading.Thread(target=main)
t.daemon = True
t.start()


def exitApp(code=0):
    print("[DEBUG] Releasing video")
    video_capture.release()
    sys.exit(code)


# Start application
app = QApplication(sys.argv)
if not camera_working:
    msg = QMessageBox.critical(
        None, "Error", "No webcam found, or webcam is too slow.")
    exitApp(1)

ex = App()
sys.exit(app.exec_())
