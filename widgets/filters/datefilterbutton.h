#ifndef DATEFILTERBUTTON_H
#define DATEFILTERBUTTON_H

#include <QPushButton>
#include <data/pour.h>

class DateFilterButton : public QPushButton
{
    Q_OBJECT
public:
    explicit DateFilterButton(QWidget *parent = 0);

    bool CheckPour(Pour*);
    void Reset(bool emitChange);

signals:
    void FilterChanged();

public slots:
    void OnClicked();

private:
    double startTime;
    int selectedIndex;
    vector<class DateOption> options;

    void setSelectedIndex(int index);
    
};

class DateOption
{
public:
    DateOption(string name, double time) { Name = name; Time = time; }
    string Name;
    double Time;
};

#endif // DATEFILTERBUTTON_H
