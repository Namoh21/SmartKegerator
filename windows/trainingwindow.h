#ifndef TRAININGWINDOW_H
#define TRAININGWINDOW_H

#include <QMainWindow>
#include "opencv2/core/core.hpp"

namespace Ui {
class TrainingWindow;
}

class TrainingWindow : public QMainWindow
{
    Q_OBJECT
    
public:
    explicit TrainingWindow(QWidget *parent = 0);
    ~TrainingWindow();

    static TrainingWindow* Instance;

    static void ShowWindow(class User* user);
    void HideWindow();

signals:
    void updateCamImageSignal();

protected:
    void closeEvent(QCloseEvent *);

private slots:
    void updateCamImageSlot();

    void on_closeButton_clicked();
    
    void on_testButton_clicked();

    void on_exitButton_clicked();

private:
    void shown(class User* user);
    class User* trainingUser;
    bool searching;

    void startSearching();

    int lastFaceCount;

    void updateCamImage();
    static void handleFrame();

    cv::Size cameraDisplaySize;
    cv::Mat displayMat;
    QImage qImage;

    Ui::TrainingWindow *ui;
};

#endif // TRAININGWINDOW_H
