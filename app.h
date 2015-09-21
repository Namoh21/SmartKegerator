#include <QApplication>

using namespace std;

class App : public QObject
{
    Q_OBJECT
public:
    App();
    static App* Instance;

    static bool Fullscreen;
    static int WindowX, WindowY;
    static double StartTime;
    static QString CssStyle;

    void Shutdown();
};
