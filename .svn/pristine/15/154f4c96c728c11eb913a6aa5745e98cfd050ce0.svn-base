#include <windows/pouringwindow.h>
#include <ui_pouringwindow.h>
#include <QtConcurrentRun>
#include <QCloseEvent>
#include <QTimer>
#include <QTime>
#include <time.h>
#include <shared.h>
#include <stdio.h>
#include <sys/stat.h>
#include <app.h>
#include <raspicamcv/raspicvcam.h>
#include <managers/facialrecognitionmanager.h>
#include <managers/flowmetermanager.h>
#include <managers/gpiomanager.h>
#include <managers/recordingmanager.h>
#include <windows/mainwindow.h>
#include <data/settings.h>
#include <data/keg.h>
#include <data/user.h>
#include <data/pour.h>
#include <data/constants.h>

#include "opencv2/core/core.hpp"
#include "opencv2/contrib/contrib.hpp"
#include "opencv2/highgui/highgui.hpp"
#include "opencv2/imgproc/imgproc.hpp"
#include "opencv2/imgproc/imgproc_c.h"
#include "opencv2/objdetect/objdetect.hpp"


PouringWindow* PouringWindow::Instance;

double ticksPerLiter;

double ounces, liters, price;

int closeWindowAfterSeconds = 5;

bool pouring = false;
bool foundNewUser = false;
bool logPours = true;
int photoFrequency = 5;

Pour* currentPour;
User *currentUser;


PouringWindow::PouringWindow(QWidget *parent) :
    QMainWindow(parent),
    ui(new Ui::PouringWindow)
{
    ui->setupUi(this);
    setStyleSheet(App::CssStyle);

    QObject::connect(FlowMeterManager::Instance, SIGNAL(PourStarted()), this, SLOT(onPourStarted()));
    QObject::connect(FlowMeterManager::Instance, SIGNAL(PourFinished()), this, SLOT(onPourFinished()));
    QObject::connect(FlowMeterManager::Instance, SIGNAL(FlowMeterTicked()), this, SLOT(onFlowMeterTick()));

    connect(&updateTimer, SIGNAL(timeout()), this, SLOT(updateUI()));
    connect(this, SIGNAL(updateCamImageSignal()), this, SLOT(updateCamImageSlot()));

    ticksPerLiter = Settings::GetDouble("ticksPerLiter");
    logPours = Settings::GetBool("logPours");
    photoFrequency = Settings::GetInt("pourPhotoFrequency");

    currentUser = User::UnknownUser;
    currentPour = NULL;

    ui->usersComboBox->view()->setItemDelegate(new CustomComboBoxItem(this));
    vector<User*>::iterator iter;
    for (iter = User::UsersList.begin(); iter != User::UsersList.end(); ++iter)
    {
        User* user = (*iter);
        ui->usersComboBox->addItem(QString(user->Name.c_str()));
    }
    connect(ui->usersComboBox, SIGNAL(currentIndexChanged(int)), this, SLOT(userSelectedSlot(int)));
}

void PouringWindow::onPourStarted()
{
    ShowWindow();

    closeWindowAt = -1;
    foundNewUser = false;
    pouring = true;
    currentUser = User::UnknownUser;

    currentPour = new Pour();
    currentPour->KegId = FlowMeterManager::CurrentKeg->Id;
    currentPour->UserId = -1;
    currentPour->PriceModifier = 1;

    liters = 0;
    ounces = 0;
    price = 0;

    Beer* beer = Beer::BeersById[FlowMeterManager::CurrentKeg->BeerId];

    ui->beerNameField->setText(beer->Name.c_str());
    ui->beerCompanyField->setText(beer->Company.c_str());
    int beerCount = Pour::GetPoursInLast(Constants::Day).size() + 1;
    ui->beerCountField->setText(QString("%1 beer in last 24h").arg(prettyEnding(beerCount)));
    ui->usersComboBox->setCurrentIndex(0);

    ui->finishPourButton->setText("Finish Pour");

    updateScanningText();

    startCamera();

    updateTimer.start(1000);
}

void PouringWindow::onPourFinished()
{
    if (logPours)
    {
        qDebug("Finished pour! Id: %d", Pour::NextId);

        currentPour->KegId = FlowMeterManager::CurrentKeg->Id;
        currentPour->Ticks = FlowMeterManager::Ticks;
        currentPour->PriceModifier = 1;
        currentPour->Ounces = ounces;
        Pour::AddPour(currentPour);
    }
    else
    {
        qDebug("Finished pour! Logging disabled");
        ui->beerCountField->setText(QString("Logging disabled!"));
    }

    pouring = false;

    ui->finishPourButton->setText("Close");
    ui->beerCountField->setText(QString("Enjoy your beer!"));


    closeWindowAt = (double)time(NULL) + closeWindowAfterSeconds;
}

void PouringWindow::userSelectedSlot(int index)
{
    if (index == -1)
        return;

    currentUser = User::UsersList[index];

    currentPour->UserId = currentUser->Id;
    if (pouring == false)
        Pour::SavePours();

    int beerCount = Pour::GetPoursInLast(Constants::Day, currentUser).size() + 1;
    ui->beerCountField->setText(QString("Your %1 beer today").arg(prettyEnding(beerCount)));
}

void PouringWindow::onFlowMeterTick()
{
    updateUI();

    if (FlowMeterManager::ConflictingTicks)
        ui->beerCompanyField->setText(QString("Uh oh! Both beers detected!"));
}


void PouringWindow::updateScanningText()
{
    if (currentUser == User::UnknownUser)
    {
        int faces = FacialRecognitionManager::FaceCount;
        if (faces == 0)
            ui->scanningField->setText(QString("Scanning..."));
        else
            ui->scanningField->setText(QString("1 face detected!"));
    }
    else
        ui->scanningField->setText(QString("Hello %1!").arg(currentUser->Name.c_str()));
}

void PouringWindow::updateUI()
{
    if (pouring == false)
    {
        double now = time(NULL);
        if (closeWindowAt < now)
            HideWindow();
        return;
    }

    updateScanningText();

    if (foundNewUser)
    {
        int userIndex = std::find(User::UsersList.begin(), User::UsersList.end(), currentUser) - User::UsersList.begin();
        ui->usersComboBox->setCurrentIndex(userIndex);
        foundNewUser = false;
    }

    liters = FlowMeterManager::Ticks / (double)ticksPerLiter;
    ounces = liters * Constants::OuncesPerLiter;
    price = FlowMeterManager::CurrentKeg->GetPrice(liters);

    ui->volumePouredField->setText(QString("%1oz").arg(QString::number(ounces, 'f', 1)));
    ui->priceField->setText(QString("$%1").arg(QString::number(price, 'f', 2)));
}

QString PouringWindow::prettyEnding(int val)
{
    if (val == 11 || val == 12 || val == 13)
        return QString("%1th").arg(val);
    if ((val % 10) == 1)
        return QString("%1st").arg(val);
    if ((val % 10) == 2)
        return QString("%1nd").arg(val);
    if ((val % 10) == 3)
        return QString("%1rd").arg(val);
    return QString("%1th").arg(val);
}

void PouringWindow::on_finishPourButton_clicked()
{
    if (pouring)
        FlowMeterManager::Instance->FinishPour();
    else
        HideWindow();
}

void PouringWindow::closeEvent(QCloseEvent *event)
{
    HideWindow();
    event->ignore();
}

void PouringWindow::ShowWindow()
{
    if (isHidden() == false)
        return;

    MainWindow::Instance->HideWindow();

    if (App::Fullscreen)
        showFullScreen();
    else
    {
        move(App::WindowX, App::WindowY);
        show();
    }
}

void PouringWindow::HideWindow()
{
    stopCamera();

    currentPour = NULL;

    ui->cameraDisplay->clear();

    updateTimer.stop();

    MainWindow::Instance->ShowWindow();

    if (isHidden())
        return;

    hide();
}

PouringWindow::~PouringWindow()
{
    delete ui;
}


void PouringWindow::handleFrame()
{
    FacialRecognitionManager::HandleFrame();
    RecordingManager::HandleFrame();

    if (FacialRecognitionManager::FoundUserId > -1)
    {
        currentUser = User::UsersById[FacialRecognitionManager::FoundUserId];
        foundNewUser = true;
    }

    // Draw FPS
    double fps = (double)RaspiCvCam::FrameCount / difftime(time(NULL), RaspiCvCam::CameraStartedAt);
    string fpsText = QString("FPS: %1").arg(QString::number(fps, 'f', 1)).toStdString();
    putText(RaspiCvCam::ImageMat, fpsText, Point(3, RaspiCvCam::SourceHeight - 5), FONT_HERSHEY_PLAIN, 0.8f, CV_RGB(255,255,255), 1.0);

    PouringWindow::Instance->updateCamImage();
}


void PouringWindow::startCamera()
{
    string videoLocation = QString(Settings::GetString("pourVideoLocation").c_str()).arg(currentPour->Id).toStdString();
    RecordingManager::StartRecording(videoLocation);

    FacialRecognitionManager::StartRecognition();

    RaspiCvCam::StartCamera(&PouringWindow::handleFrame);
}

void PouringWindow::stopCamera()
{
    RecordingManager::StopRecording();

    FacialRecognitionManager::StopRecognition();

    RaspiCvCam::StopCamera();

}

void PouringWindow::updateCamImage()
{
    cv::resize(RaspiCvCam::ImageMat, displayMat, cv::Size(ui->cameraDisplay->size().width(), ui->cameraDisplay->size().height()));
    qImage = QImage((uchar*)displayMat.data, displayMat.cols, displayMat.rows, displayMat.step, QImage::Format_RGB888);
    emit updateCamImageSignal();
}

void PouringWindow::updateCamImageSlot()
{
    QPixmap qp = QPixmap::fromImage(qImage);
    ui->cameraDisplay->setPixmap(qp);//.scaled(frameWidth, frameHeight, Qt::IgnoreAspectRatio, Qt::SmoothTransformation));
}
