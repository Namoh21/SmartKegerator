#include <managers/facialrecognitionmanager.h>
#include <managers/gpiomanager.h>
#include <QApplication>
#include <data/user.h>
#include <data/settings.h>
#include <raspicamcv/raspicvcam.h>
#include "opencv2/contrib/contrib.hpp"
#include <QtConcurrentRun>


CascadeClassifier FacialRecognitionManager::QuickFaceCascade;
CascadeClassifier FacialRecognitionManager::FaceCascade;
CascadeClassifier FacialRecognitionManager::EyesCascade;
CascadeClassifier FacialRecognitionManager::GlassesCascade;
Ptr<FaceRecognizer> FacialRecognitionManager::FaceRec = createFisherFaceRecognizer(0);

vector< Rect_<int> > FacialRecognitionManager::Faces;
int FacialRecognitionManager::FaceCount = 0;
Mat FacialRecognitionManager::FaceMat;
Mat FacialRecognitionManager::FaceResizedMat;
Mat FacialRecognitionManager::SourceMat;
bool FacialRecognitionManager::IsTraining = false;
bool FacialRecognitionManager::Trained = false;
bool FacialRecognitionManager::SearchForFaces = false;
bool FacialRecognitionManager::IdentifyFaces = false;


int FacialRecognitionManager::FoundUserId = -1;
bool FacialRecognitionManager::RunningRecognition = false;

void FacialRecognitionManager::Init()
{
    // Face rec
    string face_cascade_loc = Settings::GetString("facialRecFaceCascadeXML");
    string quick_face_cascade_loc = Settings::GetString("facialRecQuickFaceCascadeXML");
    string eyes_cascade_loc = Settings::GetString("facialRecEyesCascadeXML");
    string glasses_cascade_loc = Settings::GetString("facialRecGlassesCascadeXML");

    if( !FaceCascade.load( face_cascade_loc ) ){ qDebug("ERROR: Face cascade model not loaded : %s",face_cascade_loc.c_str()); };
    if( !QuickFaceCascade.load( quick_face_cascade_loc ) ){ qDebug("ERROR: Quick Face cascade model not loaded : %s",quick_face_cascade_loc.c_str()); };
    if( !EyesCascade.load( eyes_cascade_loc ) ){ qDebug("ERROR: Eyes cascade model not loaded : %s",eyes_cascade_loc.c_str());  };
    if( !GlassesCascade.load( glasses_cascade_loc ) ){ qDebug("ERROR: Glasses cascade model not loaded : %s",glasses_cascade_loc.c_str());  };

    qDebug("FacialRecognitionManager cascades loaded");

    if (Settings::GetBool("trainFacialRecOnStart"))
        Train();

    qDebug("FacialRecognitionManager inited");
}

void FacialRecognitionManager::StartDetection()
{
    Reset();
    SearchForFaces = true;
}

void FacialRecognitionManager::StartRecognition()
{
    Reset();
    SearchForFaces = true;
    IdentifyFaces = true;
}

void FacialRecognitionManager::StopRecognition()
{
    SearchForFaces = false;
    IdentifyFaces = false;
}

void FacialRecognitionManager::Reset()
{
    Faces.clear();
    FaceCount = 0;
    FoundUserId = -1;
}

void FacialRecognitionManager::HandleFrame()
{
    // If facial rec has finished, kick off a new one!
    if (RunningRecognition == false)
    {
        RunningRecognition = true;

        SourceMat = RaspiCvCam::ImageMat.clone();

        QtConcurrent::run(doRecognition);
    }

    bool drawFaces = true;
    if (drawFaces)
    {
        // Scale for UI
        //cv::resize(RaspiCvCam::ImageMat, displayMat, cv::Size(frameWidth, frameHeight));

        //double scale = (double)frameWidth/(double)RaspiCvCam::SourceWidth;

        if (FaceCount > 0)
        {
            Rect face_i = Faces[0];

            // draw frame
            rectangle(RaspiCvCam::ImageMat, face_i, CV_RGB(255, 255 ,255), 1);

            // draw name
            //User user = detectUser();

            if (IdentifyFaces)
            {
                string userName = User::UsersById[FoundUserId]->Name;//User == NULL ? "Unknown" : :user.Name;
                int pos_x = std::max(face_i.tl().x, 0);
                int pos_y = std::max(face_i.tl().y - 3, 0);
                putText(RaspiCvCam::ImageMat, userName, Point(pos_x, pos_y), FONT_HERSHEY_PLAIN, 1.0, CV_RGB(255,255,255), 1.0);
            }
        }
    }
}


void FacialRecognitionManager::doRecognition()
{
    if (SearchForFaces)
    {
        // Skip while camera is starting up
        if (RaspiCvCam::FrameCount > 10)
        {
            // detect faces
            FaceCascade.detectMultiScale(SourceMat, Faces, 1.2, 3, CV_HAAR_SCALE_IMAGE, Size(50,50), Size(150,150));

            FaceCount = Faces.size();
        }
    }

    if (IdentifyFaces && Trained && FaceCount > 0)
    {
        FaceMat = SourceMat(Faces[0]);

        cv::resize(FaceMat, FaceResizedMat, Size(100, 100), 1.0, 1.0, CV_INTER_NN); //INTER_CUBIC);

        cv::cvtColor(FaceResizedMat, FaceResizedMat, CV_RGB2GRAY);

        equalizeHist(FaceResizedMat, FaceResizedMat);

        double confidence = 0.0;
        int prediction = FaceRec->predict(FaceResizedMat);//, prediction, confidence);

        int confidenceThreshold = 4500;
        if (prediction > - 1)// && confidence > confidenceThreshold)
        {
            //qDebug("found userId: %d, with %f confidence", prediction - 1, confidence);
            FoundUserId = prediction - 1;
        }
        else
        {
            //qDebug("did not find user! userId: %d, with %f confidence", prediction - 1, confidence);
        }
    }

    RunningRecognition = false;
}

void FacialRecognitionManager::Train()
{
    Trained = false;
    IsTraining = true;
    QtConcurrent::run(doTraining);
}

void FacialRecognitionManager::doTraining()
{
    qDebug("Acquirring facerec images");
    vector<Mat> images;
    vector<int> ids;

    vector<User*>::iterator iter;
    for(iter = User::UsersList.begin(); iter != User::UsersList.end(); iter++)
    {
        User* user = (*iter);
        if (user->ImagePaths.size() == 0)
            continue;

        vector<string>::iterator strIter;
        for(strIter = user->ImagePaths.begin(); strIter != user->ImagePaths.end(); strIter++)
        {
            ids.push_back(user->Id + 1);
            string path = (*strIter);
            Mat img = imread(path, CV_LOAD_IMAGE_GRAYSCALE);
            //qDebug("Loaded face image %dx%d: %s", img.size().width, img.size().height, path.c_str());
            images.push_back(img);
        }
    }

    // train the model with your nice collection of pictures
    //qDebug("Beginning facerec training %d profiles", images.size());
    FaceRec->train(images, ids);
    qDebug("Facerec training completed");

    Trained = true;
    IsTraining = false;
}
