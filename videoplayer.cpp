#include "videoplayer.h"

VideoPlayer::VideoPlayer(QObject *parent)
 : QThread(parent)
{
    playing = false;
    TotalFrames = 0;
    CurrentFrame = 0;
}

bool VideoPlayer::LoadVideo(string filename)
{
    capture.open(filename);
    if (capture.isOpened())
    {
        FrameRate = (int) capture.get(CV_CAP_PROP_FPS);
        TotalFrames = (int) capture.get(CV_CAP_PROP_FRAME_COUNT);
        CurrentFrame = 0;
        //qDebug("Framerate: %d", frameRate);
        if (FrameRate <= 0)
        {
            capture.release();
            capture = NULL;
            return false;
        }
        return true;
    }
    else
        return false;
}

void VideoPlayer::Play()
{
    if (!isRunning())
    {
        if (IsPlaying() == false)
            playing = true;

        start(LowPriority);
    }
}

void VideoPlayer::run()
{
    int delay = (1000/FrameRate);
    while(playing)
    {
        if (!capture.read(frame))
            break;

        if (frame.channels()== 3){
            cv::cvtColor(frame, RGBframe, CV_BGR2RGB);
            img = QImage((const unsigned char*)(RGBframe.data),
                              RGBframe.cols,RGBframe.rows,QImage::Format_RGB888);
        }
        else
        {
            img = QImage((const unsigned char*)(frame.data),
                                 frame.cols,frame.rows,QImage::Format_Indexed8);
        }
        CurrentFrame++;
        emit processedImageSignal(img);
        this->msleep(delay);
    }

    playing = false;
    CurrentFrame = 0;

    // blackscreen
    //img = QImage(1,1,QImage::Format_Indexed8);
    //img.fill(0);
    //emit processedImageSignal(img);

    emit videoFinished();
}

VideoPlayer::~VideoPlayer()
{
    mutex.lock();
    Stop();
    capture.release();
    condition.wakeOne();
    mutex.unlock();
    wait();
}

void VideoPlayer::Stop()
{
    playing = false;
}

void VideoPlayer::msleep(int ms)
{
    struct timespec ts = { ms / 1000, (ms % 1000) * 1000 * 1000 };
    nanosleep(&ts, NULL);
}

bool VideoPlayer::IsPlaying() const
{
    return this->playing;
}
