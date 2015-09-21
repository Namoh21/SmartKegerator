#ifndef USERS_H
#define USERS_H

#include <data/dataobject.h>
#include <string>

using namespace std;

class User : DataObject
{
public:
    static User* UnknownUser;
    static vector<User*> UsersList;
    static map<int, User*> UsersById;
    static void LoadUsers();
    static void SaveUsers();

    static User* AddUser(string name);

    User();
    User(StringMap);

    void ParseStringMap(StringMap data);
    string ToString();

    static int NextId;

    int Id;
    string Name;
    vector<string> ImagePaths;
    int NextImageId;
};


#endif // USERS_H
