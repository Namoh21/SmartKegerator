#include <windows/historywindow.h>
#include <ui_historywindow.h>
#include <app.h>
#include <shared.h>
#include <QStyledItemDelegate>
#include <QtConcurrentRun>
#include <QFont>
#include <QCloseEvent>
#include <managers/flowmetermanager.h>
#include <windows/mainwindow.h>
#include <windows/keyboarddialog.h>
#include <data/pour.h>
#include <data/constants.h>
#include <data/settings.h>
#include <QMessageBox>
#include <QCleanlooksStyle>

#include "opencv2/core/core.hpp"
#include "opencv2/contrib/contrib.hpp"
#include "opencv2/highgui/highgui.hpp"
#include "opencv2/imgproc/imgproc.hpp"
#include "opencv2/imgproc/imgproc_c.h"
#include "opencv2/objdetect/objdetect.hpp"

using namespace std;

HistoryWindow* HistoryWindow::Instance;

map<GraphDisplayType, string> DisplayTypeNames;
vector<string> dowLabels;

HistoryWindow::HistoryWindow(QWidget *parent) :
    QMainWindow(parent),
    ui(new Ui::HistoryWindow)
{
    ui->setupUi(this);
    setStyleSheet(App::CssStyle);

    if (DisplayTypeNames.size() == 0)
    {
        dowLabels.push_back("Sunday");
        dowLabels.push_back("Monday");
        dowLabels.push_back("Tuesday");
        dowLabels.push_back("Wednesday");
        dowLabels.push_back("Thursday");
        dowLabels.push_back("Friday");
        dowLabels.push_back("Saturday");

        DisplayTypeNames[POURS_BY_USER] = "Pours by User";
        DisplayTypeNames[POURS_BY_BEER] = "Pours by Beer";
        DisplayTypeNames[POURS_BY_DOW] = "Pours by DOW";
    }

    connect(FlowMeterManager::Instance, SIGNAL(PourFinished()), this, SLOT(pourFinishedSlot()));
    connect(FlowMeterManager::Instance, SIGNAL(PourStarted()), this, SLOT(pourStartedSlot()));
    connect(ui->scrollPane, SIGNAL(SelectionChanged(int)), this, SLOT(setSelectedIndex(int)));

    // Filters
    connect(ui->userFilter, SIGNAL(FilterChanged()), this, SLOT(onFilterChanged()));
    connect(ui->kegFilter, SIGNAL(FilterChanged()), this, SLOT(onFilterChanged()));
    connect(ui->beerFilter, SIGNAL(FilterChanged()), this, SLOT(onFilterChanged()));
    connect(ui->dateFilter, SIGNAL(FilterChanged()), this, SLOT(onFilterChanged()));

    setVideoProgress(0);
    selectedIndex = -1;
    selectedPour = NULL;
    graphDisplayType = POURS_BY_USER;

    ui->usersComboBox->view()->setItemDelegate(new CustomComboBoxItem(this));
    connect(ui->usersComboBox, SIGNAL(currentIndexChanged(int)), this, SLOT(userSelectedSlot(int)));

    vector<User*>::iterator iter;
    for (iter = User::UsersList.begin(); iter != User::UsersList.end(); ++iter)
        ui->usersComboBox->addItem(QString((*iter)->Name.c_str()));

    ui->usersComboBox->setCurrentIndex(-1);

    ui->graphComboBox->view()->setItemDelegate(new CustomComboBoxItem(this));
    connect(ui->graphComboBox, SIGNAL(currentIndexChanged(int)), this, SLOT(graphTypeSelectedSlot(int)));

    setGraphMode(false);

    videoPlayer = new VideoPlayer();
    connect(videoPlayer, SIGNAL(processedImageSignal(QImage)), this, SLOT(updateVideoImageSlot(QImage)));
    connect(videoPlayer, SIGNAL(videoFinished()), this, SLOT(videoFinished()));
}

void HistoryWindow::SetUser(User* user)
{
    ui->userFilter->SetUser(user);
}

void HistoryWindow::setGraphMode(bool graph)
{
    graphMode = graph;
    ui->graphFrame->setVisible(graph);
    ui->graphComboBox->setVisible(graph);
    ui->backgroundTile_3->setVisible(graph);

    ui->scrollPane->setVisible(graph == false);
    ui->previewLabel->setVisible(graph == false);
    ui->infoLabel->setVisible(graph == false);
    ui->usersComboBox->setVisible(graph == false);
    ui->backgroundTile_2->setVisible(graph == false);
    ui->videoPrgoressBar->setVisible(graph == false);
}

void HistoryWindow::userSelectedSlot(int index)
{
    if (index == -1 || selectedIndex == -1)
        return;

    User* user = User::UsersList[index];
    if (selectedPour->UserId == user->Id)
        return;

    selectedPour->UserId = user->Id;
    Pour::SavePours();

    bool resetIndex = ui->userFilter->IsAll() == false;
    updatePours(resetIndex);
}

void HistoryWindow::pourStartedSlot()
{
    if (isHidden())
        return;

    videoPlayer->Stop();
    //HideWindow();
}

void HistoryWindow::pourFinishedSlot()
{
    if (isHidden())
        return;

    updatePours();
}


void HistoryWindow::on_deleteButton_clicked()
{
    if (selectedIndex == -1)
        return;

    QMessageBox::StandardButton response = QMessageBox::question(this, "Confirm", "Are you sure you want to remove this pour?", QMessageBox::Yes | QMessageBox::No);

    if (response != QMessageBox::Yes)
        return;

    if (KeyboardDialog::VerifyPassword() == false)
        return;

    Pour::RemovePour(selectedPour);

    updatePours();
}


void HistoryWindow::updatePours(bool resetIndex)
{
    if (resetIndex)
        ui->scrollPane->SetSelectedIndex(-1);
    currentPours.clear();
    vector<string> labels;
    int size = Pour::AllPours.size();
    for(unsigned int i=0; i<size; i++)
    {
        Pour* pour = Pour::AllPours[size - i - 1];

        // Because pours are sequential, date filter failing means we can bail entirely
        if (ui->dateFilter->CheckPour(pour) == false)
            break;

        if (ui->userFilter->CheckPour(pour) == false ||
            ui->kegFilter->CheckPour(pour) == false ||
            ui->beerFilter->CheckPour(pour) == false)
            continue;

        currentPours.push_back(pour);

        Keg* keg = Keg::KegsById[pour->KegId];
        Beer* beer = Beer::BeersById[keg->BeerId];
        User* user = User::UsersById[pour->UserId];

        QString str = QString("%1 - %2 - %3\n$%4 - %5oz - %6")
                .arg(i + 1)
                .arg(user->Name.c_str())
                .arg(beer->Name.c_str())
                .arg(QString::number(pour->Price, 'f', 2))
                .arg(QString::number(pour->Ounces, 'f', 2))
                .arg(pour->TimeString.c_str());
        labels.push_back(str.toStdString());
    }

    ui->resultCountLabel->setText(QString("Results: %1").arg(labels.size()));

    // Update list
    ui->scrollPane->SetOptions(labels);

    updateAvailableGraphTypes();
}

// hack
bool editing = false;
void HistoryWindow::updateAvailableGraphTypes()
{
    AvailableGraphTypes.clear();

    if (ui->userFilter->Count > 1)
        AvailableGraphTypes.push_back(POURS_BY_USER);
    if (ui->kegFilter->Count > 1 && ui->beerFilter->Count > 1)
        AvailableGraphTypes.push_back(POURS_BY_BEER);
    AvailableGraphTypes.push_back(POURS_BY_DOW);

    // Update graph
    ui->graphComboBox->clear();
    int newIndex = 0;
    editing = true;
    for(int i=0; i<AvailableGraphTypes.size(); i++)
    {
        GraphDisplayType graphType = AvailableGraphTypes[i];
        ui->graphComboBox->addItem(QString(DisplayTypeNames[graphType].c_str()));
        if (graphType == graphDisplayType)
            newIndex = i;
    }
    editing = false;
    ui->graphComboBox->setCurrentIndex(-1);
    ui->graphComboBox->setCurrentIndex(newIndex);
}

void HistoryWindow::graphTypeSelectedSlot(int index)
{
    if (index == -1 || editing)
        return;

    graphDisplayType = AvailableGraphTypes[index];

    updateGraph();
}

void HistoryWindow::updateGraph()
{
    if (graphMode == false)
        return;

    switch(graphDisplayType)
    {
        case POURS_BY_BEER:
        {
            map<string, double> values;
            for (int i=0; i<currentPours.size(); i++)
            {
                Pour* pour = currentPours[i];
                Keg* keg = Keg::KegsById[pour->KegId];
                Beer* beer = Beer::BeersById[keg->BeerId];
                values[beer->Name.c_str()]++;
            }
            ui->graphFrame->ShowBarChart(values);
        }
        break;
        case POURS_BY_DOW:
        {
            vector<double> values;
            for (int i=0; i<7; i++)
                values.push_back(0);

            for (int i=0; i<currentPours.size(); i++)
            {
                Pour* pour = currentPours[i];
                time_t timeObj = pour->Time;
                tm *pourTime = localtime(&timeObj);
                values[pourTime->tm_wday]++;
            }
            ui->graphFrame->ShowBarChart(dowLabels, values);
        }
        break;
        case POURS_BY_USER:
        {
            map<string, double> values;
            for (int i=0; i<currentPours.size(); i++)
            {
                Pour* pour = currentPours[i];
                User* user = User::UsersById[pour->UserId];
                values[user->Name.c_str()]++;
            }
            ui->graphFrame->ShowBarChart(values);
        }
        break;
    }
}


void HistoryWindow::setSelectedIndex(int index)
{
    selectedIndex = index;

    if (selectedIndex == -1)
    {
        selectedPour = NULL;

        float totalOunces = 0;
        QString topDrinker = QString("-");

        vector<Pour*>::iterator iter;
        for(iter = Pour::AllPours.begin(); iter != Pour::AllPours.end(); iter++)
        {
            Pour* pour = (*iter);
            totalOunces += pour->Ounces;
        }

        QString infoString = QString("Total Pours: %1\nTotal Pints: %2\nTotal Volume: %3oz\nTop Drinker: %4")
                .arg(Pour::AllPours.size())
                .arg(QString::number(totalOunces / Constants::OuncesPerLiter, 'f', 2))
                .arg(QString::number(totalOunces, 'f', 2))
                .arg(topDrinker);

        ui->infoLabel->setText(infoString);
        ui->usersComboBox->setEnabled(false);
        ui->usersComboBox->setCurrentIndex(-1);

        videoPlayer->Stop();
        ui->previewLabel->clear();
    }
    else
    {
        selectedPour = currentPours[selectedIndex];
        Keg* keg = Keg::KegsById[selectedPour->KegId];
        Beer* beer = Beer::BeersById[keg->BeerId];
        User* user = User::UsersById[selectedPour->UserId];

        int userIndex = std::find(User::UsersList.begin(), User::UsersList.end(), user) - User::UsersList.begin();
        ui->usersComboBox->setEnabled(true);
        ui->usersComboBox->setCurrentIndex(userIndex);

        // Time - User
        // Beer - Price - Ounces
        QString str = QString("Time: %1\nBeer: %2\nby %3\nPrice: $%4\nOunces: %5oz\nTicks: %6")
                .arg(selectedPour->TimeString.c_str())
                .arg(beer->Name.c_str())
                .arg(beer->Company.c_str())
                .arg(QString::number(selectedPour->Price, 'f', 2))
                .arg(QString::number(selectedPour->Ounces, 'f', 2))
                .arg(selectedPour->Ticks);
        ui->infoLabel->setText(str);

        string videoLocation = QString(Settings::GetString("pourVideoLocation").c_str()).arg(selectedPour->Id).toStdString();
        if (videoPlayer->LoadVideo(videoLocation.c_str()))
            videoPlayer->Play();
    }
}

void HistoryWindow::setVideoProgress(float progress)
{
    ui->videoPrgoressBar->setGeometry(ui->videoPrgoressBar->x(), ui->videoPrgoressBar->y(), progress * ui->previewLabel->size().width(), ui->videoPrgoressBar->size().height());
}

void HistoryWindow::updateVideoImageSlot(QImage img)
{
    if (img.isNull() == false)
    {
        ui->previewLabel->setAlignment(Qt::AlignCenter);
        ui->previewLabel->setPixmap(QPixmap::fromImage(img).scaled(ui->previewLabel->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
        float pos = videoPlayer->TotalFrames == 0 ? 0 : (float)videoPlayer->CurrentFrame / (float)videoPlayer->TotalFrames;
        setVideoProgress(pos);
    }
}

void HistoryWindow::videoFinished()
{
    // hide display
    //ui->previewLabel->setVisible(false);
}

void HistoryWindow::on_closeButton_clicked()
{
    HideWindow();
}


void HistoryWindow::on_listButton_clicked()
{
    setGraphMode(false);
}

void HistoryWindow::on_graphButton_clicked()
{
    setGraphMode(true);
    updateGraph();
}

void HistoryWindow::resetFilters()
{
    ui->userFilter->Reset(false);
    ui->kegFilter->Reset(false);
    ui->beerFilter->Reset(false);
    ui->dateFilter->Reset(false);

    updatePours();
}
void HistoryWindow::on_resetFiltersButton_clicked()
{
    resetFilters();
}

void HistoryWindow::onFilterChanged()
{
    updatePours();
}

void HistoryWindow::closeEvent(QCloseEvent *event)
{
    HideWindow();
    event->ignore();
}

void HistoryWindow::shown()
{
    setGraphMode(false);

    resetFilters();

    ui->usersComboBox->clear();

    vector<User*>::iterator iter;
    for (iter = User::UsersList.begin(); iter != User::UsersList.end(); ++iter)
        ui->usersComboBox->addItem(QString((*iter)->Name.c_str()));

    ui->usersComboBox->setCurrentIndex(-1);
}

void HistoryWindow::ShowWindow()
{
    if (HistoryWindow::Instance == NULL)
        HistoryWindow::Instance = new HistoryWindow();

    if (HistoryWindow::Instance->isHidden() == false)
        return;

    if (App::Fullscreen)
        HistoryWindow::Instance->showFullScreen();
    else
    {
        HistoryWindow::Instance->move(App::WindowX, App::WindowY);
        HistoryWindow::Instance->show();
    }

    HistoryWindow::Instance->shown();
}

void HistoryWindow::HideWindow()
{
    videoPlayer->Stop();

    MainWindow::Instance->ShowWindow();
    if (isHidden())
        return;
    hide();
}

HistoryWindow::~HistoryWindow()
{
    delete videoPlayer;
    delete ui;
}
