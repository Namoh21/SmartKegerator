#ifndef RECORDINGMANAGER_H
#define RECORDINGMANAGER_H

#include "opencv2/core/core.hpp"
#include "opencv2/highgui/highgui.hpp"
#include "QTime"

using namespace std;
using namespace cv;

class RecordingManager
{
public:
    static void Init();

    static void StartRecording(string fileLocation);
    static void StopRecording();

    static void HandleFrame();

private:
    static void doWrite();

    static VideoWriter* videoWriter;

    static QTime lastVideoFrameAt;
    static bool writingFrame;
    static Mat videoFrame;

    static int framerate;
    static int eachFrameDelay;
    static int framesToSkip;
    static int droppedFrameCount;
};

#endif // RECORDINGMANAGER_H
