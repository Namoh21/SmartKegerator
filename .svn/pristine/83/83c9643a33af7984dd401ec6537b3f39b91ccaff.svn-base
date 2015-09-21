#include "keyboarddialog.h"
#include "ui_keyboarddialog.h"
#include <QPushButton>
#include <QCloseEvent>
#include <data/settings.h>
#include "app.h"

KeyboardDialog* KeyboardDialog::Instance;
double KeyboardDialog::lastLoginTime = -1;
double KeyboardDialog::loginSessionDuration = 60;

KeyboardDialog::KeyboardDialog(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::KeyboardDialog)
{
    ui->setupUi(this);
    setStyleSheet(App::CssStyle);

    buttons.push_back(ui->pushButton_Q);
    buttons.push_back(ui->pushButton_W);
    buttons.push_back(ui->pushButton_E);
    buttons.push_back(ui->pushButton_R);
    buttons.push_back(ui->pushButton_T);
    buttons.push_back(ui->pushButton_Y);
    buttons.push_back(ui->pushButton_U);
    buttons.push_back(ui->pushButton_I);
    buttons.push_back(ui->pushButton_O);
    buttons.push_back(ui->pushButton_P);
    buttons.push_back(ui->pushButton_A);
    buttons.push_back(ui->pushButton_S);
    buttons.push_back(ui->pushButton_D);
    buttons.push_back(ui->pushButton_F);
    buttons.push_back(ui->pushButton_G);
    buttons.push_back(ui->pushButton_H);
    buttons.push_back(ui->pushButton_J);
    buttons.push_back(ui->pushButton_K);
    buttons.push_back(ui->pushButton_L);
    buttons.push_back(ui->pushButton_Z);
    buttons.push_back(ui->pushButton_X);
    buttons.push_back(ui->pushButton_C);
    buttons.push_back(ui->pushButton_V);
    buttons.push_back(ui->pushButton_B);
    buttons.push_back(ui->pushButton_N);
    buttons.push_back(ui->pushButton_M);

    keyboardKeys.push_back("q");
    keyboardKeys.push_back("w");
    keyboardKeys.push_back("e");
    keyboardKeys.push_back("r");
    keyboardKeys.push_back("t");
    keyboardKeys.push_back("y");
    keyboardKeys.push_back("u");
    keyboardKeys.push_back("i");
    keyboardKeys.push_back("o");
    keyboardKeys.push_back("p");
    keyboardKeys.push_back("a");
    keyboardKeys.push_back("s");
    keyboardKeys.push_back("d");
    keyboardKeys.push_back("f");
    keyboardKeys.push_back("g");
    keyboardKeys.push_back("h");
    keyboardKeys.push_back("j");
    keyboardKeys.push_back("k");
    keyboardKeys.push_back("l");
    keyboardKeys.push_back("z");
    keyboardKeys.push_back("x");
    keyboardKeys.push_back("c");
    keyboardKeys.push_back("v");
    keyboardKeys.push_back("b");
    keyboardKeys.push_back("n");
    keyboardKeys.push_back("m");

    keyboardCapsKeys.push_back("Q");
    keyboardCapsKeys.push_back("W");
    keyboardCapsKeys.push_back("E");
    keyboardCapsKeys.push_back("R");
    keyboardCapsKeys.push_back("T");
    keyboardCapsKeys.push_back("Y");
    keyboardCapsKeys.push_back("U");
    keyboardCapsKeys.push_back("I");
    keyboardCapsKeys.push_back("O");
    keyboardCapsKeys.push_back("P");
    keyboardCapsKeys.push_back("A");
    keyboardCapsKeys.push_back("S");
    keyboardCapsKeys.push_back("D");
    keyboardCapsKeys.push_back("F");
    keyboardCapsKeys.push_back("G");
    keyboardCapsKeys.push_back("H");
    keyboardCapsKeys.push_back("J");
    keyboardCapsKeys.push_back("K");
    keyboardCapsKeys.push_back("L");
    keyboardCapsKeys.push_back("Z");
    keyboardCapsKeys.push_back("X");
    keyboardCapsKeys.push_back("C");
    keyboardCapsKeys.push_back("V");
    keyboardCapsKeys.push_back("B");
    keyboardCapsKeys.push_back("N");
    keyboardCapsKeys.push_back("M");

    numberKeys.push_back("1");
    numberKeys.push_back("2");
    numberKeys.push_back("3");
    numberKeys.push_back("4");
    numberKeys.push_back("5");
    numberKeys.push_back("6");
    numberKeys.push_back("7");
    numberKeys.push_back("8");
    numberKeys.push_back("9");
    numberKeys.push_back("0");

    numberDecimalKeys.push_back("1");
    numberDecimalKeys.push_back("2");
    numberDecimalKeys.push_back("3");
    numberDecimalKeys.push_back("4");
    numberDecimalKeys.push_back("5");
    numberDecimalKeys.push_back("6");
    numberDecimalKeys.push_back("7");
    numberDecimalKeys.push_back("8");
    numberDecimalKeys.push_back("9");
    numberDecimalKeys.push_back("0");
    numberDecimalKeys.push_back(".");

    numberDatetimeKeys.push_back("1");
    numberDatetimeKeys.push_back("2");
    numberDatetimeKeys.push_back("3");
    numberDatetimeKeys.push_back("4");
    numberDatetimeKeys.push_back("5");
    numberDatetimeKeys.push_back("6");
    numberDatetimeKeys.push_back("7");
    numberDatetimeKeys.push_back("8");
    numberDatetimeKeys.push_back("9");
    numberDatetimeKeys.push_back("0");
    numberDatetimeKeys.push_back("/");
    numberDatetimeKeys.push_back(":");

    symbolKeys.push_back(".");
    symbolKeys.push_back(",");
    symbolKeys.push_back("!");
    symbolKeys.push_back("@");
    symbolKeys.push_back("#");
    symbolKeys.push_back("$");
    symbolKeys.push_back("%");
    symbolKeys.push_back("^");
    symbolKeys.push_back("&");
    symbolKeys.push_back("*");
    symbolKeys.push_back("(");
    symbolKeys.push_back(")");
    symbolKeys.push_back("-");
    symbolKeys.push_back("_");
    symbolKeys.push_back("=");
    symbolKeys.push_back("+");
    symbolKeys.push_back("/");
    symbolKeys.push_back("?");
    symbolKeys.push_back("<");
    symbolKeys.push_back(">");
    symbolKeys.push_back("|");
    symbolKeys.push_back(":");
    symbolKeys.push_back(";");
    symbolKeys.push_back("[");
    symbolKeys.push_back("]");
    symbolKeys.push_back("~");

    // Init keys
    for(int i=0; i<buttons.size(); i++)
    {
        QPushButton* button = buttons[i];
        connect(button, SIGNAL(clicked()), this, SLOT(onKeyClicked()));
    }
}

void KeyboardDialog::onKeyClicked()
{
    QPushButton* button = (QPushButton*)(QObject::sender());

    for(int i=0; i<(int)buttons.size(); i++)
    {
        if (buttons[i] == button)
        {
            insertString(currentKeys->at(i));
            return;
        }
    }
}

string KeyboardDialog::GetString(string label, string startingInput, KeyboardInputMode mode, bool lockMode, bool password)
{
    if (KeyboardDialog::Instance == NULL)
        KeyboardDialog::Instance = new KeyboardDialog();

    if (App::Fullscreen)
        KeyboardDialog::Instance->showFullScreen();
    else
    {
        KeyboardDialog::Instance->move(App::WindowX, App::WindowY);
        KeyboardDialog::Instance->show();
    }

    KeyboardDialog::Instance->setWindowTitle(QString(label.c_str()));
    KeyboardDialog::Instance->ui->label->setText(label.c_str());
    KeyboardDialog::Instance->ui->label->setSelection(0, label.length());
    KeyboardDialog::Instance->original = startingInput;
    KeyboardDialog::Instance->ui->inputField->setText(startingInput.c_str());
    KeyboardDialog::Instance->ui->pushButton_ChangeKeyboard->setVisible(lockMode == false);
    KeyboardDialog::Instance->ui->inputField->setEchoMode(password ? QLineEdit::Password : QLineEdit::Normal);
    KeyboardDialog::Instance->shift = true;
    KeyboardDialog::Instance->cancelled = true;
    KeyboardDialog::Instance->setMode(mode);

    KeyboardDialog::Instance->exec();

    return KeyboardDialog::Instance->ui->inputField->text().toStdString();
}

bool KeyboardDialog::TryGetString(string &val, string label, string startingInput, KeyboardInputMode mode, bool lockMode, bool password)
{
    val = GetString(label, startingInput, mode, lockMode, password);
    return KeyboardDialog::Instance->cancelled == false;
}

double KeyboardDialog::GetDouble(string label, double startingValue)
{
    string startingValueStr = QString::number(startingValue, 'f', 2).toStdString();
    string str = GetString(label, startingValueStr, NUMBER_DECIMAL_INPUT, true);
    double val = QString(str.c_str()).toDouble();
    return val;
}

bool KeyboardDialog::TryGetDouble(double &val, string label, double startingInput)
{
    val = GetDouble(label, startingInput);
    return KeyboardDialog::Instance->cancelled == false;
}

int KeyboardDialog::GetInt(string label, int startingValue)
{
    string startingValueStr = QString::number(startingValue).toStdString();
    string str = GetString(label, startingValueStr, NUMBER_INPUT, true);
    int val = QString(str.c_str()).toInt();
    return val;
}

bool KeyboardDialog::TryGetInt(int &val, string label, int startingInput)
{
    val = GetInt(label, startingInput);
    return KeyboardDialog::Instance->cancelled == false;
}

bool KeyboardDialog::VerifyPassword()
{
    // Check for last login
    double now = time(NULL);
    if (now < lastLoginTime + loginSessionDuration)
    {
        lastLoginTime = now;
        return true;
    }
    string input = KeyboardDialog::GetString("Enter Password", "", NUMBER_INPUT, true, true);
    bool correct = input == Settings::GetString("password");
    if (correct)
        lastLoginTime = now;
    return correct;
}

void KeyboardDialog::setMode(KeyboardInputMode mode)
{
    currentMode = mode;
    updateKeys();
}

void KeyboardDialog::updateKeys()
{
    bool showShift = false;
    bool showSpace = false;

    switch(currentMode)
    {
        case KEYBOARD_INPUT:
            if (shift)
                currentKeys = &keyboardCapsKeys;
            else
                currentKeys = &keyboardKeys;
            showShift = showSpace = true;
        break;
        case NUMBER_DECIMAL_INPUT:
            currentKeys = &numberDecimalKeys;
        break;
        case NUMBER_DATETIME_INPUT:
            currentKeys = &numberDatetimeKeys;
            showSpace = true;
        break;
        case NUMBER_INPUT:
            currentKeys = &numberKeys;
        break;
        case SYMBOL_INPUT:
            currentKeys = &symbolKeys;
        break;
    }

    ui->pushButton_Shift->setVisible(showShift);
    ui->pushButton_Space->setVisible(showSpace);

    for(int i=0; i<(int)buttons.size(); i++)
    {
        if (i < (int)currentKeys->size())
        {
            buttons[i]->setVisible(true);
            string str = currentKeys->at(i);
            buttons[i]->setText(str.c_str());
        }
        else
            buttons[i]->setVisible(false);
    }
}

void KeyboardDialog::insertString(string in)
{
    ui->inputField->insert(QString(in.c_str()));

    if (shift)
    {
        shift = false;
        updateKeys();
    }
}

void KeyboardDialog::on_pushButton_Space_clicked()
{
    ui->inputField->insert(QString(" "));
}

void KeyboardDialog::on_pushButton_Delete_clicked()
{
    ui->inputField->backspace();
}

void KeyboardDialog::on_pushButton_Shift_clicked()
{
    shift = !shift;
    updateKeys();
}

void KeyboardDialog::on_pushButton_ChangeKeyboard_clicked()
{
    switch(currentMode)
    {
        case KEYBOARD_INPUT:
            setMode(NUMBER_INPUT);
        return;
        case NUMBER_INPUT:
        case NUMBER_DECIMAL_INPUT:
        case NUMBER_DATETIME_INPUT:
            setMode(SYMBOL_INPUT);
        return;
        case SYMBOL_INPUT:
            setMode(KEYBOARD_INPUT);
        return;
    }
}

void KeyboardDialog::on_pushButton_Cancel_clicked()
{
    ui->inputField->setText(QString(original.c_str()));
    hide();
}

void KeyboardDialog::on_pushButton_Enter_clicked()
{
    cancelled = false;
    hide();
}

void KeyboardDialog::on_inputField_returnPressed()
{
    cancelled = false;
    hide();
}

void KeyboardDialog::closeEvent(QCloseEvent *event)
{
    ui->inputField->setText(QString(original.c_str()));
    event->ignore();
}

KeyboardDialog::~KeyboardDialog()
{
    delete ui;
}
