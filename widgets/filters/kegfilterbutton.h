#ifndef KEGFILTERBUTTON_H
#define KEGFILTERBUTTON_H

#include <QPushButton>
#include <data/pour.h>
#include <data/keg.h>

class KegFilterButton : public QPushButton
{
    Q_OBJECT
public:
    explicit KegFilterButton(QWidget *parent = 0);

    bool CheckPour(Pour*);
    void Reset(bool emitChange);
    int Count;

signals:
    void FilterChanged();

public slots:
    void OnClicked();

private:
    map<Keg*, bool> selectedKegs;
    
};

#endif // KEGFILTERBUTTON_H
