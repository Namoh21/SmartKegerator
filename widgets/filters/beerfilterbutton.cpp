#include "beerfilterbutton.h"
#include <windows/optionselectdialog.h>

BeerFilterButton::BeerFilterButton(QWidget *parent) :
    QPushButton(parent)
{
    connect(this, SIGNAL(clicked()), this, SLOT(OnClicked()));
    Reset(false);
}

void BeerFilterButton::Reset(bool emitChange)
{
    selectedBeers.clear();
    Count = Beer::BeersById.size();
    setText("All Beers");
    if (emitChange)
        emit FilterChanged();
}

bool BeerFilterButton::CheckPour(Pour *pour)
{
    if (selectedBeers.size() == 0)
        return true;
    Keg* keg = Keg::KegsById[pour->KegId];
    Beer* beer = Beer::BeersById[keg->BeerId];
    return selectedBeers[beer];
}

void BeerFilterButton::OnClicked()
{
    vector<Beer*> beers;
    vector<string> beerStrings;
    vector<bool> vals;

    map<int, Beer*>::iterator iter;
    for (iter = Beer::BeersById.begin(); iter != Beer::BeersById.end(); ++iter)
    {
        Beer* beer = iter->second;
        beers.push_back(beer);
        beerStrings.push_back(beer->Name);
        bool selected = selectedBeers.size() == 0 || selectedBeers[beer];
        vals.push_back(selected);
    }

    if (OptionSelectDialog::TryGetChoices(&vals, "Select Beers", beerStrings) == false) return;

    selectedBeers.clear();
    Count = 0;
    for(int i=0; i<vals.size(); i++)
    {
        Beer* beer = beers[i];
        selectedBeers[beer] = vals[i];
        if (vals[i])
            Count++;
    }

    if (Count == beers.size())
    {
        Reset(true);
        return;
    }

    if (Count == 1)
    {
        for(int i=0; vals.size(); i++)
            if (vals[i])
            {
                setText(QString("%1").arg(beers[i]->Name.c_str()));
                break;
            }
    }
    else
        setText(QString("%1 Beers").arg(Count));

    emit FilterChanged();
}
