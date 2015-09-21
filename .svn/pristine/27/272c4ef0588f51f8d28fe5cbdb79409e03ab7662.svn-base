#include "kegfilterbutton.h"
#include <windows/optionselectdialog.h>

KegFilterButton::KegFilterButton(QWidget *parent) :
    QPushButton(parent)
{
    connect(this, SIGNAL(clicked()), this, SLOT(OnClicked()));
    Reset(false);
}

void KegFilterButton::Reset(bool emitChange)
{
    selectedKegs.clear();
    Count = Keg::KegsById.size();
    setText("All Kegs");
    if (emitChange)
        emit FilterChanged();
}

bool KegFilterButton::CheckPour(Pour *pour)
{
    if (selectedKegs.size() == 0)
        return true;
    Keg* keg = Keg::KegsById[pour->KegId];
    return selectedKegs[keg];
}

string getKegString(Keg* keg)
{
    Beer* beer = Beer::BeersById[keg->BeerId];
    return QString("%1 %2\nFilled: %3").arg(beer->Company.c_str()).arg(beer->Name.c_str()).arg(keg->DateBought.c_str()).toStdString();
}

void KegFilterButton::OnClicked()
{
    vector<Keg*> kegs;
    vector<string> kegStrings;
    vector<bool> vals;

    map<int, Keg*>::reverse_iterator iter;
    for (iter = Keg::KegsById.rbegin(); iter != Keg::KegsById.rend(); ++iter)
    {
        Keg* keg = iter->second;
        Beer* beer = Beer::BeersById[keg->BeerId];
        kegs.push_back(keg);
        kegStrings.push_back(QString("%1 %2\n%3").arg(beer->Company.c_str()).arg(beer->Name.c_str()).arg(keg->DateBought.c_str()).toStdString());
        bool selected = selectedKegs.size() == 0 || selectedKegs[keg];
        vals.push_back(selected);
    }

    if (OptionSelectDialog::TryGetChoices(&vals, "Select Kegs", kegStrings) == false) return;

    selectedKegs.clear();
    Count = 0;
    for(int i=0; i<vals.size(); i++)
    {
        Keg* keg = kegs[i];
        selectedKegs[keg] = vals[i];
        if (vals[i])
            Count++;
    }

    if (Count == kegs.size())
    {
        Reset(true);
        return;
    }

    if (Count == 1)
    {
        for(int i=0; vals.size(); i++)
            if (vals[i])
            {
                Keg* keg = kegs[i];
                setText(QString("Bought:/n%1").arg(keg->DateBought.c_str()));
                break;
            }
    }
    else
        setText(QString("%1 Kegs").arg(Count));

    emit FilterChanged();
}
