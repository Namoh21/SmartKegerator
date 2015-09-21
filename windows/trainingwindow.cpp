#include "trainingwindow.h"
#include "ui_trainingwindow.h"
#include "data/settings.h"
#include "data/payment.h"
#include "data/keg.h"
#include "data/beer.h"
#include "data/pour.h"
#include "data/user.h"
#include "app.h"
#include "stdio.h"
#include "raspicamcv/raspicvcam.h"
#include "sys/stat.h"
#include "sys/types.h"
#include <QCloseEvent>
#include <QMessageBox>
#include <QtConcurrentRun>
#include <managers/facialrecognitionmanager.h>
#include <managers/gpiomanager.h>
#include <windows/mainwindow.h>
#include <windows/historywindow.h>
#include "opencv2/objdetect/objdetect.hpp"
#include "opencv2/highgui/highgui.hpp"
#include "opencv2/imgproc/imgproc.hpp"

TrainingWindow* TrainingWindow::Instance;

TrainingWindow::TrainingWindow(QWidget *parent) :
    QMainWindow(parent),
    ui(new Ui::TrainingWindow)
{
    ui->setupUi(this);
    setStyleSheet(App::CssStyle);

    connect(this, SIGNAL(updateCamImageSignal()), this, SLOT(updateCamImageSlot()));

}

void TrainingWindow::shown(User* user)
{
    trainingUser = user;
    searching = false;

    ui->deleteButton->setVisible(trainingUser != NULL);
    ui->saveButton->setVisible(trainingUser != NULL);
    ui->defaultButton->setVisible(trainingUser != NULL);

    ui->faceDisplay->setVisible(false);
    ui->addButton->setVisible(false);
    ui->countdownLabel->setVisible(false);

    if (trainingUser != NULL)
        ui->nameLabel->setText(QString("User: %1").arg(trainingUser->Name.c_str()));
    else
        ui->nameLabel->setText("");

    lastFaceCount = -1;
    ui->faceCountLabel->setText("Starting up");

    FacialRecognitionManager::StartDetection();

    RaspiCvCam::StartCamera(&TrainingWindow::handleFrame);
}

void TrainingWindow::handleFrame()
{
    FacialRecognitionManager::HandleFrame();

    TrainingWindow::Instance->updateCamImage();
}

void TrainingWindow::updateCamImage()
{
    cv::resize(RaspiCvCam::ImageMat, displayMat, cv::Size(ui->cameraDisplay->size().width(), ui->cameraDisplay->size().height()));
    qImage = QImage((uchar*)displayMat.data, displayMat.cols, displayMat.rows, displayMat.step, QImage::Format_RGB888);
    emit updateCamImageSignal();
}

void TrainingWindow::updateCamImageSlot()
{
    QPixmap qp = QPixmap::fromImage(qImage);
    ui->cameraDisplay->setPixmap(qp);//.scaled(frameWidth, frameHeight, Qt::IgnoreAspectRatio, Qt::SmoothTransformation));

    if (lastFaceCount != FacialRecognitionManager::FaceCount)
    {
        lastFaceCount = FacialRecognitionManager::FaceCount;
        if (lastFaceCount == 0)
            ui->faceCountLabel->setText("No Faces Found");
        else
            ui->faceCountLabel->setText(QString("%1 Face%2 Found").arg(lastFaceCount).arg(lastFaceCount > 1 ? "s" : ""));
    }

    if (searching)
    {

    }

}

void TrainingWindow::startSearching()
{
    searching = true;
    ui->faceDisplay->setVisible(true);
    ui->addButton->setVisible(true);
    ui->countdownLabel->setVisible(true);

    ui->statusLabel->setVisible(false);
    ui->mainButton->setVisible(false);
}

void TrainingWindow::on_exitButton_clicked()
{
    HideWindow();
}


void TrainingWindow::on_testButton_clicked()
{
    /*
    if (RaspiCvCam::CameraOn)
    {
        RaspiCvCam::StopCamera();
        GPIOManager::EnableCameraLights(false);
        updateLearningButtons();
        return;
    }

    if (userInited == false)
    {
        Myoffset_pct.x = 0.3 * 100.0;
        Myoffset_pct.y = Myoffset_pct.x;

        Mydest_sz.x = 100;
        Mydest_sz.y = Mydest_sz.x;

        qualityType.push_back(CV_IMWRITE_JPEG_QUALITY);
        qualityType.push_back(90);
        userInited = true;
    }

    foundCroppedImage = false;
    searching = false;

    FacialRecognitionManager::Faces.clear();
    FacialRecognitionManager::FaceCount = 0;

    RaspiCvCam::UseColor = false;
    RaspiCvCam::FrameUpdatedCallback = &handleFrame2;
    RaspiCvCam::StartCamera();

    GPIOManager::EnableCameraLights(true);
    */
}


void TrainingWindow::ShowWindow(User* user)
{
    if (TrainingWindow::Instance == NULL)
        TrainingWindow::Instance = new TrainingWindow();

    if (TrainingWindow::Instance->isHidden() == false)
        return;

    if (App::Fullscreen)
        TrainingWindow::Instance->showFullScreen();
    else
    {
        TrainingWindow::Instance->move(App::WindowX, App::WindowY);
        TrainingWindow::Instance->show();
    }
    TrainingWindow::Instance->shown(user);
}

void TrainingWindow::closeEvent(QCloseEvent *event)
{
    HideWindow();
    event->ignore();
}

void TrainingWindow::on_closeButton_clicked()
{
    HideWindow();
}

void TrainingWindow::HideWindow()
{
    MainWindow::Instance->ShowWindow();
    RaspiCvCam::StopCamera();
    if (isHidden())
        return;
    hide();
}

TrainingWindow::~TrainingWindow()
{
    delete ui;
}
