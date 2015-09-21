#ifndef TEMPSENSORMANAGER_H
#define TEMPSENSORMANAGER_H

#include <QApplication>
#include <QProcess>
#include <QTimer>

using namespace std;

class Graph;

class TempSensorManager : public QObject
{
    Q_OBJECT
public:
    static TempSensorManager* Instance;
    static Graph *TempGraph, *HumGraph, *LiquidTempGraph;
    static double Temperature;
    static double LiquidTemperature;
    static double Humidity;
    static void Init();
    static void Shutdown();

    TempSensorManager();

signals:
    void TempUpdated();

private slots:
    void onTempData();
    void onResetTick();
    void onLiquidTempData(int returnCode);
    void onLiquidTempTick();

private:
    void resetSensor();
    int tempSensorPin;
    double lastTempUpdateAt;
    int resetState;
    int resetThreshold;
    QTimer resetTimer, liquidTempTimer;
    QProcess *tempProcess, *liquidTempProcess;

    string tempSensorCommand, tempCleanupCommand, liquidTempSensorCommand;
};

#endif // TEMPSENSORMANAGER_H
