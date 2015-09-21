#ifndef BASEWINDOW_H
#define BASEWINDOW_H

#include <QMainWindow>

using namespace std;

class BaseWindow
{
public:

    static BaseWindow* CurrentWindow;

    static void ShowWindow(BaseWindow* window);
    static void HideWindow(BaseWindow* window);

protected:
    static BaseWindow* windowStack[10];

    virtual void onShown() = 0;
    virtual void onHidden() = 0;
};

#endif // BASEWINDOW_H
