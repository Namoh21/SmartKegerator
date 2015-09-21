#include "userfilterbutton.h"
#include <windows/optionselectdialog.h>
#include <data/pour.h>
#include <data/user.h>

UserFilterButton::UserFilterButton(QWidget *parent) :
    QPushButton(parent)
{
    connect(this, SIGNAL(clicked()), this, SLOT(OnClicked()));
    Reset(false);
}

void UserFilterButton::SetUser(User* user)
{
    selectedUsers.clear();
    selectedUsers[user] = true;
    setText(QString("%1").arg(user->Name.c_str()));
    emit FilterChanged();
}

void UserFilterButton::Reset(bool emitChange)
{
    selectedUsers.clear();
    Count = User::UsersById.size();
    setText("All Users");
    if (emitChange)
        emit FilterChanged();
}

bool UserFilterButton::CheckPour(Pour *pour)
{
    if (selectedUsers.size() == 0)
        return true;
    User* user = User::UsersById[pour->UserId];
    return selectedUsers[user];
}

bool UserFilterButton::IsAll()
{
    return Count == User::UsersById.size();
}

void UserFilterButton::OnClicked()
{
    vector<User*> users;
    vector<string> userStrings;
    vector<bool> vals;

    map<int, User*>::iterator iter;
    for (iter = User::UsersById.begin(); iter != User::UsersById.end(); ++iter)
    {
        User* user = iter->second;
        users.push_back(user);
        userStrings.push_back(user->Name);
        bool selected = selectedUsers.size() == 0 || selectedUsers[user];
        vals.push_back(selected);
    }

    if (OptionSelectDialog::TryGetChoices(&vals, "Select Users", userStrings) == false) return;

    selectedUsers.clear();
    Count = 0;
    for(int i=0; i<vals.size(); i++)
    {
        User* user = users[i];
        selectedUsers[user] = vals[i];
        if (vals[i])
            Count++;
    }

    if (Count == users.size())
    {
        Reset(true);
        return;
    }

    if (Count == 1)
    {
        for(int i=0; vals.size(); i++)
            if (vals[i])
            {
                setText(QString("%1").arg(users[i]->Name.c_str()));
                break;
            }
    }
    else
        setText(QString("%1 Users").arg(Count));

    emit FilterChanged();
}
