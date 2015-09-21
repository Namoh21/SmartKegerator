#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QTimer>
#include <QLabel>
#include <QProcess>
#include <queue>
#include <windows/basewindow.h>

using namespace std;

class BeerDisplay;
class Keg;


namespace Ui {
class MainWindow;
}

class MainWindow : public QMainWindow, BaseWindow
{
    Q_OBJECT
    
public:
    explicit MainWindow(QWidget *parent = 0);
    ~MainWindow();

    static MainWindow* Instance;

    void ShowWindow();
    void HideWindow();

    void ResetGraph();

private slots:
    void updateUI();
    void onTempData();

    void on_closeButton_clicked();
    void on_settingsButton_clicked();
    void on_historyButton_clicked();
    void on_usersButton_clicked();

    void on_temperatureButton_clicked();

    void on_humidityButton_clicked();

protected:
    void closeEvent(QCloseEvent *);

    void onShown();
    void onHidden();

private:
    Ui::MainWindow *ui;
    QTimer updateTimer;
    bool hidden;

    BeerDisplay *leftDisplay;
    BeerDisplay *rightDisplay;

    void onQuit();
    void updateTime();
    void updateBeers();

};


// Beer display
class BeerDisplay
{
public:
    BeerDisplay(QWidget* keg,
                QLabel *logo,
                QLabel *name,
                QLabel *company,
                QLabel *city,
                QLabel *price,
                QLabel *abv,
                QLabel *ibu,
                QLabel *bought,
                QLabel *empty,
                QLabel *remaining);

    QLabel* nameField;
    QLabel* companyField;
    QLabel* cityField;
    QLabel* ibuField;
    QLabel* abvField;
    QLabel* priceField;
    QLabel* boughtField;
    QLabel* emptyField;
    QLabel* remainingField;

    QLabel* logoLabel;
    int kegHeight, kegY;
    QWidget* kegFill;

    int lastId;

    void update(Keg* keg);

    void setKegFill(double percent);
};

#endif // MAINWINDOW_H
