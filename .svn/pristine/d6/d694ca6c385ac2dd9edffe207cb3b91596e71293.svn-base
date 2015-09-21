#ifndef UTILITIES_H
#define UTILITIES_H

#include <QString>

using namespace std;

class Utilities
{
public:
    static string GetFullTimeString(double time)
    {
        time_t timeObj = time;
        tm *pTime = localtime(&timeObj);

        static const QString amQstring = QString("am");
        static const QString pmQstring = QString("pm");

        QString mins = QString(pTime->tm_min < 10 ? "0%1" : "%1").arg(pTime->tm_min);

        return QString("%1/%2/%3 %4:%5%6")
                .arg(pTime->tm_mon + 1)
                .arg(pTime->tm_mday)
                .arg(pTime->tm_year +  1900)
                .arg((pTime->tm_hour%12) == 0 ? 12 : (pTime->tm_hour%12))
                .arg(mins)
                .arg(pTime->tm_hour < 12 ? amQstring : pmQstring)
                .toStdString();
    }
};

#endif // UTILITIES_H
