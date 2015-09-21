#include <app.h>
#include <iostream>
#include <fstream>
#include <raspicamcv/raspicvcam.h>
#include <data/settings.h>
#include <data/keg.h>
#include <data/beer.h>
#include <data/user.h>
#include <data/pour.h>
#include <data/payment.h>
#include <managers/facialrecognitionmanager.h>
#include <managers/tempsensormanager.h>
#include <managers/flowmetermanager.h>
#include <managers/gpiomanager.h>
#include <managers/recordingmanager.h>
#include <windows/mainwindow.h>
#include <windows/pouringwindow.h>

App* App::Instance;

bool App::Fullscreen;
int App::WindowX, App::WindowY;
double App::StartTime;
QString App::CssStyle;


App::App() : QObject()
{
    qDebug("Starting app");

    // Set globals
    Instance = this;
    StartTime = time(NULL);
    Fullscreen = Settings::GetBool("windowFullscreen");
    WindowX = Settings::GetInt("windowX");
    WindowY = Settings::GetInt("windowY");

    // Load CSS
    string cssFilename = Settings::GetString("cssFile");
    ifstream file(cssFilename.c_str());
    string str;
    if (!file)
        qDebug("Failed to load css file! %s", cssFilename.c_str());
    else
        while(getline(file, str))
            CssStyle.append(str.c_str());

    // Load data
    Beer::LoadBeers();
    Keg::LoadKegs();
    User::LoadUsers();
    Pour::LoadPours();
    Payment::LoadPayments();

    // Start managers
    RaspiCvCam::Init();
    FacialRecognitionManager::Init();
    GPIOManager::Init();
    TempSensorManager::Init();
    FlowMeterManager::Init();
    RecordingManager::Init();

    // Create windows
    MainWindow::Instance = new MainWindow();
    PouringWindow::Instance = new PouringWindow();
    qDebug("Windows created");

    // Show main window
    MainWindow::Instance->ShowWindow();
}

void App::Shutdown()
{
    TempSensorManager::Shutdown();
    FlowMeterManager::Shutdown();

    RaspiCvCam::Destroy();
    qDebug("App shut down!");
}
