#include <windows/mainwindow.h>
#include <ui_mainwindow.h>
#include <data/settings.h>
#include <data/constants.h>
#include <managers/tempsensormanager.h>
#include <QtConcurrentRun>
#include <QCloseEvent>
#include <QDebug>
#include <time.h>
#include <string>
#include <iostream>
#include <stdio.h>
#include <queue>
#include <app.h>
#include <cmath>
#include <data/keg.h>
#include <data/beer.h>
#include <data/user.h>
#include <data/constants.h>
#include <widgets/graph/graph.h>
#include <windows/userswindow.h>
#include <windows/historywindow.h>
#include <windows/settingswindow.h>
#include <windows/keyboarddialog.h>
#include <windows/optionselectdialog.h>

MainWindow* MainWindow::Instance;

MainWindow::MainWindow(QWidget *parent) :
    QMainWindow(parent),
    ui(new Ui::MainWindow)
{
    ui->setupUi(this);
    setStyleSheet(App::CssStyle);

    ui->tempField->setAttribute(Qt::WA_TransparentForMouseEvents);
    ui->tempLabel->setAttribute(Qt::WA_TransparentForMouseEvents);
    ui->humidityField->setAttribute(Qt::WA_TransparentForMouseEvents);
    ui->humidityLabel->setAttribute(Qt::WA_TransparentForMouseEvents);

    ui->graphFrame->AddGraph(TempSensorManager::TempGraph);
    ui->graphFrame->AddGraph(TempSensorManager::HumGraph);
    //ui->graphFrame->AddGraph(TempSensorManager::LiquidTempGraph);

    // Set up displays
    leftDisplay = new BeerDisplay(ui->leftKegFill,
                                  ui->leftLogo,
                                  ui->leftBeerNameField,
                                  ui->leftBeerCompanyField,
                                  ui->leftCityField,
                                  ui->leftPriceField,
                                  ui->leftAbvField,
                                  ui->leftIbuField,
                                  ui->leftBoughtField,
                                  ui->leftEmptyField,
                                  ui->remainingLeftField);

    rightDisplay = new BeerDisplay(ui->rightKegFill,
                                   ui->rightLogo,
                                   ui->rightBeerNameField,
                                   ui->rightBeerCompanyField,
                                   ui->rightCityField,
                                   ui->rightPriceField,
                                   ui->rightAbvField,
                                   ui->rightIbuField,
                                   ui->rightBoughtField,
                                   ui->rightEmptyField,
                                   ui->remainingRightField);


    connect(&updateTimer, SIGNAL(timeout()), this, SLOT(updateUI()));
    updateTimer.start(1000);

    connect(TempSensorManager::Instance, SIGNAL(TempUpdated()), this, SLOT(onTempData()));
}

void MainWindow::onShown()
{

}

void MainWindow::onHidden()
{

}

void MainWindow::onTempData()
{
    ui->tempField->setText(QString::number(ceil(TempSensorManager::Temperature-0.5), 'f', 0));
    ui->humidityField->setText(QString::number(ceil(TempSensorManager::Humidity-0.5), 'f', 0));
}

void MainWindow::on_historyButton_clicked()
{
    HistoryWindow::Instance->ShowWindow();
    HideWindow();
}

void MainWindow::on_usersButton_clicked()
{
    UsersWindow::Instance->ShowWindow();
    HideWindow();
}

void MainWindow::on_settingsButton_clicked()
{
    if (KeyboardDialog::VerifyPassword() == false)
        return;

    SettingsWindow::ShowWindow();
    HideWindow();
}

void MainWindow::ResetGraph()
{
    this->ui->graphFrame->Reset();
}

double nextUpdate = 0;// * 60;
void MainWindow::updateUI()
{
    if (hidden)
        return;

    updateTime();
    ui->graphFrame->update();

    double now = time(NULL);
    if (now > nextUpdate)
    {
        updateBeers();
        nextUpdate = now + 60;
    }
}

QString getUptimeString(double uptimed)
{
    int weeks = uptimed / (double)Constants::Week;
    int uptime = fmod(uptimed, Constants::Week);
    int days = (uptime / Constants::Day) % 7;
    int hours = (uptime / Constants::Hour) % 24;
    int mins = (uptime / Constants::Minute) % 60;
    int secs = uptime % Constants::Minute;
    if (uptimed >= Constants::Week)
        return QString("%1w%2d%3h%4m%5s").arg(weeks).arg(days).arg(hours).arg(mins).arg(secs);
    if (uptime >= Constants::Day)
        return QString("%1d%2h%3m%4s").arg(days).arg(hours).arg(mins).arg(secs);
    if (uptime >= Constants::Hour)
        return QString("%1h%2m%3s").arg(hours).arg(mins).arg(secs);
    if (uptime >= Constants::Minute)
        return QString("%1m%2s").arg(mins).arg(secs);
    return QString("%1s").arg(secs);
}

void MainWindow::updateTime()
{
    time_t timeObj;
    time(&timeObj);
    tm *pTime = localtime(&timeObj);

    QString mins = QString(pTime->tm_min < 10 ? "0%1" : "%1").arg(pTime->tm_min);

    double now = time(NULL);
    double uptime = now - App::StartTime;

    ui->uptimeField->setText(QString("%1/%2/%3 %4:%5 - Uptime: %6")
                             .arg(pTime->tm_mon + 1).arg(pTime->tm_mday).arg(pTime->tm_year - 100)
                             .arg((pTime->tm_hour%12) == 0 ? 12 : (pTime->tm_hour%12)).arg(mins)
                             .arg(getUptimeString(uptime)));
}


void MainWindow::updateBeers()
{
    // Update displays
    leftDisplay->update(Keg::LeftKeg);
    rightDisplay->update(Keg::RightKeg);

    ui->leftBeerStatsFrame->SetKeg(Keg::LeftKeg);
    ui->rightBeerStatsFrame->SetKeg(Keg::RightKeg);
}

void MainWindow::on_temperatureButton_clicked()
{
    ui->graphFrame->ShowGraph(TempSensorManager::TempGraph);
}

void MainWindow::on_humidityButton_clicked()
{
    ui->graphFrame->ShowGraph(TempSensorManager::HumGraph);
}

void MainWindow::ShowWindow()
{
    hidden = false;
    ui->leftBeerStatsFrame->AutoScrollEnabled = true;
    ui->rightBeerStatsFrame->AutoScrollEnabled = true;
    updateBeers();
    updateUI();

    if (App::Fullscreen)
        showFullScreen();
    else
    {
        move(App::WindowX, App::WindowY);
        if (isFullScreen())
            showNormal();
        else
            show();
    }
}

void MainWindow::HideWindow()
{
    hidden = true;
    ui->leftBeerStatsFrame->AutoScrollEnabled = false;
    ui->rightBeerStatsFrame->AutoScrollEnabled = false;
    //if (isHidden())
    //    return;
    //hide();
    //updateTimer.stop();
}

void MainWindow::onQuit()
{
    qDebug("Quitting!");
    updateTimer.stop();
    App::Instance->Shutdown();
}

void MainWindow::on_closeButton_clicked()
{
    onQuit();
    QCoreApplication::quit();
}


void MainWindow::closeEvent(QCloseEvent *event)
{
    onQuit();
    event->accept();
}

MainWindow::~MainWindow()
{
    delete ui;
}

/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// BeerDisplay
/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
BeerDisplay::BeerDisplay(QWidget* keg,
                         QLabel *logo,
                         QLabel *name,
                         QLabel *company,
                         QLabel *city,
                         QLabel *price,
                         QLabel *abv,
                         QLabel *ibu,
                         QLabel *bought,
                         QLabel *empty,
                         QLabel *remaining)
{
    lastId = -1;
    kegFill = keg;
    kegHeight = keg->height();
    kegY = keg->y();
    logoLabel = logo;
    logoLabel->setFrameShape(QFrame::NoFrame);

    nameField = name;
    companyField = company;
    cityField = city;
    priceField = price;
    abvField = abv;
    ibuField = ibu;
    boughtField = bought;
    emptyField = empty;
    remainingField = remaining;
}

void BeerDisplay::update(Keg* keg)
{
    if (keg == NULL)
    {
        setKegFill(0);
        nameField->setText("");
        companyField->setText("");
        cityField->setText("");
        priceField->setText("-");
        abvField->setText("-");
        ibuField->setText("-");
        boughtField->setText("-");
        emptyField->setText("-");
        remainingField->setText("");

        if (lastId != -1)
            logoLabel->clear();
        lastId = -1;
    }
    else
    {
        Beer* beer = Beer::BeersById[keg->BeerId];
        setKegFill(1-(keg->LitersPoured / keg->LitersCapacity));
        remainingField->setText(QString("%1").arg((int)((keg->LitersCapacity - keg->LitersPoured) * Constants::PintsPerLiter)));
        nameField->setText(beer->Name.c_str());
        companyField->setText(beer->Company.c_str());
        cityField->setText(beer->Location.c_str());
        priceField->setText(QString("$%1").arg(QString::number(keg->PricePerPint, 'f', 2)));
        abvField->setText(QString("%1%").arg(QString::number(beer->ABV, 'f', 1)));
        ibuField->setText(QString("%1").arg(beer->IBU));
        boughtField->setText(QString("%1").arg(keg->DateBought.c_str()));
        emptyField->setText(QString("%1").arg(keg->GetEmptyDate().c_str()));

        if (lastId != keg->Id)
        {
            // load image, apply alpha to it
            QPixmap input(beer->LogoPath.c_str());
            QPixmap output(logoLabel->size());
            output.fill(Qt::transparent);
            QPainter p(&output);
            p.setOpacity(Settings::GetDouble("beerLogoOpacity"));
            QSize border = output.size() - input.size();
            p.drawPixmap(0.5*border.width(), 0.5*border.height(), input);
            p.end();
            logoLabel->setPixmap(output);
        }
        lastId = keg->Id;
    }
}

void BeerDisplay::setKegFill(double percent)
{
    int newHeight = kegHeight * percent;
    kegFill->setGeometry(kegFill->x(), kegY + kegHeight - newHeight, kegFill->width(), newHeight);
}
