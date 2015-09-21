#ifndef BEERFILTERBUTTON_H
#define BEERFILTERBUTTON_H

#include <QPushButton>
#include <data/beer.h>
#include <data/pour.h>

class BeerFilterButton : public QPushButton
{
    Q_OBJECT
public:
    explicit BeerFilterButton(QWidget *parent = 0);

    bool CheckPour(Pour*);
    void Reset(bool emitChange);
    int Count;

signals:
    void FilterChanged();

public slots:
    void OnClicked();

private:
    map<Beer*, bool> selectedBeers;
    
};

#endif // BEERFILTERBUTTON_H
