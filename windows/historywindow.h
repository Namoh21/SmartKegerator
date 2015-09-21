#ifndef HISTORYWINDOW_H
#define HISTORYWINDOW_H

#include <QMainWindow>
#include <QPushButton>
#include <QGridLayout>
#include <videoplayer.h>

using namespace std;

namespace Ui {
class HistoryWindow;
}

enum GraphDisplayType { POURS_BY_USER, POURS_BY_DOW, POURS_BY_BEER};

class HistoryWindow : public QMainWindow
{
    Q_OBJECT
    
public:
    explicit HistoryWindow(QWidget *parent = 0);
    ~HistoryWindow();

    static HistoryWindow* Instance;

    static void ShowWindow();
    void HideWindow();

    void SetUser(class User* user);


    void updateVideoImage();

signals:
    void updateVideoImageSignal();

protected:
    void closeEvent(QCloseEvent *);

private slots:
    void updateVideoImageSlot(QImage img);
    void videoFinished();

    void setSelectedIndex(int pourId);
    void pourStartedSlot();
    void pourFinishedSlot();
    void userSelectedSlot(int);
    void onFilterChanged();
    void graphTypeSelectedSlot(int);

    void on_closeButton_clicked();
    void on_deleteButton_clicked();
    void on_listButton_clicked();
    void on_graphButton_clicked();
    void on_resetFiltersButton_clicked();

private:
    Ui::HistoryWindow *ui;
    bool graphMode;
    GraphDisplayType graphDisplayType;
    int selectedIndex;
    class Pour* selectedPour;
    vector<Pour*> currentPours;
    vector<GraphDisplayType> AvailableGraphTypes;

    VideoPlayer* videoPlayer;

    void shown();
    void setGraphMode(bool graph);
    void updatePours(bool resetIndex = true);
    void updateAvailableGraphTypes();
    void updateGraph();
    void resetFilters();
    void setVideoProgress(float progress);

};

#endif // HISTORYWINDOW_H
