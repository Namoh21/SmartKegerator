#ifndef VIDEOPLAYER_H
#define VIDEOPLAYER_H

#include <QMutex>
#include <QThread>
#include <QImage>
#include <QWaitCondition>
#include <opencv2/core/core.hpp>
#include <opencv2/imgproc/imgproc.hpp>
#include <opencv2/highgui/highgui.hpp>

using namespace cv;

class VideoPlayer : public QThread
{
    Q_OBJECT

public:
    VideoPlayer(QObject *parent = 0);
    ~VideoPlayer();

    bool LoadVideo(string filename);
    void Play();
    void Stop();
    bool IsPlaying() const;

    int FrameRate;
    int TotalFrames;
    int CurrentFrame;

private:
    bool playing;
    QMutex mutex;
    QWaitCondition condition;
    Mat frame;
    VideoCapture capture;
    Mat RGBframe;
    QImage img;

signals:
    void processedImageSignal(const QImage &image);
    void videoFinished();

protected:
     void run();
     void msleep(int ms);
};

#endif // VIDEOPLAYER_H
