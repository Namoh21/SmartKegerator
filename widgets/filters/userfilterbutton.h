#ifndef USERFILTERBUTTON_H
#define USERFILTERBUTTON_H

#include <QPushButton>
#include <map>

using namespace std;

class UserFilterButton : public QPushButton
{
    Q_OBJECT
public:
    explicit UserFilterButton(QWidget *parent = 0);

    bool CheckPour(class Pour*);
    void Reset(bool emitChange);
    bool IsAll();
    int Count;

    void SetUser(class User* user);

signals:
    void FilterChanged();

public slots:
    void OnClicked();

private:
    map<class User*, bool> selectedUsers;
    
};

#endif // USERFILTERBUTTON_H
