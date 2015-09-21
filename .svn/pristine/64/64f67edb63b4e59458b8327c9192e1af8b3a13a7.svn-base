#include "recordingmanager.h"
#include "raspicamcv/raspicvcam.h"
#include "data/settings.h"
#include "QtConcurrentRun"
#include "QDir"

#include "opencv2/core/core.hpp"
#include "opencv2/contrib/contrib.hpp"
#include "opencv2/imgproc/imgproc.hpp"
#include "opencv2/imgproc/imgproc_c.h"

VideoWriter* RecordingManager::videoWriter = NULL;

QTime RecordingManager::lastVideoFrameAt;
bool RecordingManager::writingFrame = false;
Mat RecordingManager::videoFrame;

int RecordingManager::framerate;
int RecordingManager::eachFrameDelay;
int RecordingManager::framesToSkip;
int RecordingManager::droppedFrameCount;

void createFolder(string folder)
{
    int lastSlash = 1;
    for (int i=0;i<10;i++)
    {
        int nextSlash = folder.find_first_of('/', lastSlash);
        if (nextSlash != -1)
        {
            string current = folder.substr(0, nextSlash);
            lastSlash = nextSlash + 1;
            if (QDir(current.c_str()).exists() == false)
            {
                QDir().mkdir(current.c_str());
                qDebug("Making logs folder: %s", current.c_str());
            }
        }
        else
            return;
    }
}

void RecordingManager::Init()
{
    framerate = Settings::GetInt("pourVideoFrameRate");
    eachFrameDelay = 1100 / framerate; // padded since on playback it seems a bit fast
    framesToSkip = Settings::GetInt("pourVideoInitialFrameDelay");

    string folder = Settings::GetString("pourVideoLocation");
    folder = folder.substr(0, folder.find_last_of('/')+1);
    createFolder(folder);

}

void RecordingManager::StartRecording(string fileLocation)
{
    if (videoWriter != NULL)
        return;

    qDebug("Starting recording: %s", fileLocation.c_str());
    videoWriter = new VideoWriter(fileLocation.c_str(), CV_FOURCC('D','I','V','3'), framerate, Size(RaspiCvCam::SourceWidth, RaspiCvCam::SourceHeight), true);
    droppedFrameCount = 0;
    writingFrame = false;
    lastVideoFrameAt.start();
}

void RecordingManager::StopRecording()
{
    qDebug("Recording finished. Frames Dropped: %d", droppedFrameCount);

    // wait until frame is finished writing
    struct timespec ts = { 5 / 1000, 0 }; // 5ms
    while(writingFrame)
        nanosleep(&ts, NULL);

    videoWriter->release();
    videoWriter = NULL;
}

void RecordingManager::HandleFrame()
{
    if (videoWriter == NULL)
        return;

    int timeSinceLastFrame = lastVideoFrameAt.elapsed();
    if (timeSinceLastFrame >= eachFrameDelay)
    {
        // Framerate adjusted here
        if (framesToSkip > 0)
            framesToSkip--;
        else
        {
            if (writingFrame == false)
            {
                lastVideoFrameAt.start();
                writingFrame = true;
                videoFrame = RaspiCvCam::ImageMat.clone();
                //cv::resize(RaspiCvCam::ImageMat, videoFrame, cv::Size(RaspiCvCam::SourceWidth, RaspiCvCam::SourceHeight));
                QtConcurrent::run(doWrite);
            }
            else
            {
                droppedFrameCount++;
                qDebug("frame Dropped! %d", droppedFrameCount);
            }
       }
    }
}

void RecordingManager::doWrite()
{
    if (videoWriter == NULL)
        return;

    cvtColor(videoFrame, videoFrame, CV_RGB2BGR);
    videoWriter->write(videoFrame);
    writingFrame = false;
}
