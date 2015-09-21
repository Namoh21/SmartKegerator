#include "datefilterbutton.h"
#include <windows/optionselectdialog.h>


DateFilterButton::DateFilterButton(QWidget *parent) :
    QPushButton(parent)
{
    if (options.size() == 0)
    {
        double day = 60 * 60 * 24;
        options.push_back(DateOption("All Time", 100000*day));
        options.push_back(DateOption("Last Day", day));
        options.push_back(DateOption("Last Week", 7 * day));
        options.push_back(DateOption("Last Month", 30 * day));
        options.push_back(DateOption("Last 6 Months", 6.f * 30.f * day));
    }

    connect(this, SIGNAL(clicked()), this, SLOT(OnClicked()));

    Reset(false);
}

void DateFilterButton::Reset(bool emitChange)
{
    setSelectedIndex(3); // month

    if (emitChange)
        emit FilterChanged();
}

bool DateFilterButton::CheckPour(Pour *pour)
{
    if (startTime > -1 && pour->Time < startTime)
        return false;

    return true;
}

void DateFilterButton::setSelectedIndex(int index)
{
    selectedIndex = index;
    startTime = (double)(time(NULL)) - options[selectedIndex].Time;
    setText(QString("%1").arg(options[selectedIndex].Name.c_str()));
}

void DateFilterButton::OnClicked()
{
    vector<string> strings;
    vector<DateOption>::iterator iter;
    for (iter = options.begin(); iter != options.end(); ++iter)
        strings.push_back(iter->Name);

    int dateChoice;
    if (OptionSelectDialog::TryGetChoice(dateChoice, "Select Time Frame", strings, selectedIndex) == false) return;

    setSelectedIndex(dateChoice);
    emit FilterChanged();
}
