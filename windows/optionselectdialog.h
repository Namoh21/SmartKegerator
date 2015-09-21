#ifndef OPTIONSELECTDIALOG_H
#define OPTIONSELECTDIALOG_H

#include <QDialog>
#include <QVBoxLayout>

using namespace std;

namespace Ui {
class OptionSelectDialog;
}

class OptionSelectDialog : public QDialog
{
    Q_OBJECT
    
public:
    explicit OptionSelectDialog(QWidget *parent = 0);
    ~OptionSelectDialog();

    static OptionSelectDialog* Instance;


    static int GetChoice(string title, vector<string> choices, int selectedIndex = -1);
    static bool TryGetChoice(int &val, string title, vector<string> choices, int selectedIndex = -1);

    static bool TryGetChoices(vector<bool> *vals, string title, vector<string> choices);

protected:
    void closeEvent(QCloseEvent *);

private slots:
    void itemClicked();
    void on_pushButton_Enter_clicked();
    void on_pushButton_Cancel_clicked();
    void on_selectNoneButton_clicked();
    void on_selectAllButton_clicked();
    void on_verticalScrollBar_valueChanged(int value);

private:
    Ui::OptionSelectDialog *ui;
    QWidget *scrollContents;
    QVBoxLayout* layout;
    int padding;
    bool cancelled;
    bool multiSelection;
    int selectedIndex;
    vector<bool> *selectedIndexes;
    vector<string> options;
    vector<QPushButton*> buttons;

    void getSelection(int selected);
    void getSelections(vector<bool> *selected);
    void init(string title, vector<string> choices);
    bool getIsSelected(int index);
    void showAndExec();
    void updateButtons();
};

#endif // OPTIONSELECTDIALOG_H
