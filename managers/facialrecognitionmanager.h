#ifndef FACIALRECOGNITIONMANAGER_H
#define FACIALRECOGNITIONMANAGER_H

#include "opencv2/core/core.hpp"
#include "opencv2/contrib/contrib.hpp"
#include "opencv2/highgui/highgui.hpp"
#include "opencv2/imgproc/imgproc.hpp"
#include "opencv2/imgproc/imgproc_c.h"
#include "opencv2/objdetect/objdetect.hpp"
#include "/home/pi/libfacerec/include/facerec.hpp"

using namespace std;
using namespace cv;

class FacialRecognitionManager
{
public:
    static void Init();

    static void StartDetection();
    static void StartRecognition();
    static void StopRecognition();

    static void HandleFrame();

    static Mat SourceMat;

    static void Train();
    static void FindFaces();


    static bool SearchForFaces;
    static bool IdentifyFaces;


    static bool IsTraining;
    static bool Trained;

    static Ptr<FaceRecognizer> FaceRec;

    static CascadeClassifier FaceCascade;
    static CascadeClassifier QuickFaceCascade;
    static CascadeClassifier EyesCascade;
    static CascadeClassifier GlassesCascade;
    static int FaceCount;
    static vector< Rect_<int> > Faces;
    static Mat FaceMat, FaceResizedMat;

    static void Reset();

    static int FoundUserId;
    static bool RunningRecognition;

private:

    static void doRecognition();
    static void doTraining();
};

#endif // FACIALRECOGNITIONMANAGER_H
