#ifndef RASPICVCAM_H
#define RASPICVCAM_H

#include <QLabel>
#include <opencv2/core/core.hpp>
#include "opencv2/highgui/highgui.hpp"
#include "opencv2/objdetect/objdetect.hpp"

using namespace std;
using namespace cv;

class RaspiCvCam
{
    typedef void (*FrameCallback) ();
public:
    static void Init();
    static void Destroy();
    static bool CameraOn;
    static int SourceHeight, SourceWidth;
    static int FrameCount;
    static QVector<QRgb> GrayscaleColorTable;
    static time_t CameraStartedAt;
    static Mat ImageMat;

    static FrameCallback FrameUpdatedCallback;

    static void StartCamera(FrameCallback callback);
    static void StopCamera();

private:
    static void enableCamera();

    static void createImages();

};

#endif // RASPICVCAM_H
