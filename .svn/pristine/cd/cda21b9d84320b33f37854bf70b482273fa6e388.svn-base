#include <managers/tempsensormanager.h>
#include <managers/gpiomanager.h>
#include <data/settings.h>
#include <widgets/graph/graph.h>
#include <app.h>
#include <time.h>
#include <QColor>
#include <cmath>

// Statics
double TempSensorManager::Temperature = -1;
double TempSensorManager::LiquidTemperature = -1;
double TempSensorManager::Humidity = -1;
Graph* TempSensorManager::TempGraph;
Graph* TempSensorManager::LiquidTempGraph;
Graph* TempSensorManager::HumGraph;
TempSensorManager* TempSensorManager::Instance;

void TempSensorManager::Init()
{
    TempSensorManager::Instance = new TempSensorManager();
}

void TempSensorManager::Shutdown()
{
    TempSensorManager::Instance->tempProcess->kill();
}


// Instance
TempSensorManager::TempSensorManager()
{
    Temperature = -1;
    Humidity = -1;

    TempGraph = new Graph(QString("Temperature"), 760/5.0, QColor(240, 100, 100, 150));
    HumGraph = new Graph(QString("Humidity"), 760/5.0, QColor(100, 200, 100, 130));
    LiquidTempGraph = new Graph(QString("Liquid Temperature"), 760/5.0, QColor(80, 80, 200, 130));

    resetState = -1;
    resetThreshold = 30;
    connect(&resetTimer, SIGNAL(timeout()), this, SLOT(onResetTick()));
    connect(&liquidTempTimer, SIGNAL(timeout()), this, SLOT(onLiquidTempTick()));

    //liquidTempTimer.start(5000);

    // Init the temp sensor
    tempSensorPin = Settings::GetInt("tempSensorPowerPin");
    GPIOManager::SetMode(tempSensorPin, "out");
    GPIOManager::Write(tempSensorPin, true);

    tempCleanupCommand = Settings::GetString("tempSensorCleanupCommand");
    tempSensorCommand = Settings::GetString("tempSensorWFICommand");
    liquidTempSensorCommand = Settings::GetString("liquidTempSensorCommand");
    tempProcess = new QProcess();
    connect(tempProcess, SIGNAL(readyReadStandardOutput()), this, SLOT(onTempData()));
    tempProcess->start(QString(tempSensorCommand.c_str()));
    lastTempUpdateAt = time(NULL);
    liquidTempProcess = NULL;

    qDebug("Temp thread created");
}

int MAX_READING_DELTA = 20;

void TempSensorManager::onTempData()
{
    string output = QString(tempProcess->readAllStandardOutput()).toStdString();

    // No data
    if (output.find("Temp =") == string::npos)
    {
        double now = time(NULL);
        double timeSince = now - lastTempUpdateAt;

        if (timeSince > resetThreshold)
            resetSensor();

        return;
    }

    int index = output.find("Temp =") + 6;
    QString qstr(output.substr(index, output.find(" *C") - index).c_str());
    double temp = qstr.toDouble();
    temp = ((9.0/5.0) * temp) + 32;
    // filter bad data
    if (Temperature == -1 || abs(int(temp - Temperature)) < MAX_READING_DELTA)
    {
        Temperature = temp;
        TempGraph->AddReading(Temperature);
    }

    index = output.find("Hum =") + 5;
    qstr = QString(output.substr(index, output.find(" %") - index).c_str());
    double hum = qstr.toDouble();
    if (Humidity == -1 || abs(int(hum - Humidity)) < MAX_READING_DELTA)
    {
        Humidity = hum;
        HumGraph->AddReading(Humidity);
    }

    lastTempUpdateAt = time(NULL);


    emit TempUpdated();
}

void TempSensorManager::resetSensor()
{
    resetState = 0;

    // Kill the process
    system(tempCleanupCommand.c_str());
    tempProcess->close();

    // Turn off the dht
    GPIOManager::Write(tempSensorPin, false);
    //qDebug("Turned off the dht!");

    resetTimer.start(1000);
}


int resetCount = 1;
void TempSensorManager::onResetTick()
{
    if (resetState == 0)
    {
        // Turn on the dht
        GPIOManager::Write(tempSensorPin, true);
        qDebug("Turned on the dht!");
        resetState++;
    }
    else
    {
        // Start the python script
        lastTempUpdateAt = time(NULL);
        tempProcess->start(QString(tempSensorCommand.c_str()));
        qDebug("Restarted temp process! %d", resetCount++);
        resetState = -1;
        resetTimer.stop();
    }
}

int waiting = 0;
void TempSensorManager::onLiquidTempTick()
{
    if (liquidTempProcess == NULL)
    {
        liquidTempProcess = new QProcess();
        connect(liquidTempProcess, SIGNAL(finished(int)), this, SLOT(onLiquidTempData(int)));
        liquidTempProcess->start(QString(liquidTempSensorCommand.c_str()));
    }
    else
        waiting++;

    if (waiting > 10)
    {
        waiting = -1000;
        qDebug("been 10 ticks!");
    }
}

int badLiquidCount = 0;
void TempSensorManager::onLiquidTempData(int returnCode)
{
    string output = QString(liquidTempProcess->readAll()).toStdString();

    if (returnCode == 0 && output.find("YES") != string::npos && output.find("t=") != string::npos)
    {
        string tempAsString = output.substr(output.find("t=")+2);
        double temp = QString(tempAsString.c_str()).toInt() / 1000.0;
        temp = ((9.0/5.0) * temp) + 32;
        if (LiquidTemperature == -1 || abs(LiquidTemperature - temp) < MAX_READING_DELTA)
        {
            LiquidTempGraph->AddReading(temp);
            LiquidTemperature = temp;
        }
    }
    else
    {
        qDebug("Got a bad reading! %d", badLiquidCount++);
    }

    liquidTempProcess->close();
    liquidTempProcess = NULL;
}
