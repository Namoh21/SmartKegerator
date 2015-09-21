#include "staticscrollarea.h"
#include <iostream>
#include <fstream>
#include <data/settings.h>
#include <QDebug>


StaticScrollArea::StaticScrollArea(QWidget *parent) :
    QFrame(parent)
{
    currentOffset = 0;
    selectedIndex = -1;

    QHBoxLayout* layout = new QHBoxLayout();
    layout->setMargin(0);
    layout->setSpacing(0);
    setLayout(layout);

    QWidget* buttonHolder = new QWidget();
    buttonLayout = new QVBoxLayout();
    buttonLayout->setMargin(0);
    buttonLayout->setSpacing(5);
    buttonLayout->setAlignment(Qt::AlignTop);
    buttonHolder->setLayout(buttonLayout);

    scrollbar = new QScrollBar();
    connect(scrollbar, SIGNAL(valueChanged(int)), this, SLOT(scrolled(int)));

    layout->addWidget(buttonHolder, Qt::AlignLeft);
    layout->addWidget(scrollbar, Qt::AlignRight);

    SetNumButtons(6);
}

void StaticScrollArea::SetNumButtons(int buttonCount)
{
    scrollbar->setRange(0, options.size()-buttonCount);

    // Create buttons
    for (unsigned int i=buttons.size();i<buttonCount; i++)
    {
        QPushButton* button = new QPushButton();
        button->setText(QString("Button %1").arg(i));
        button->setMinimumHeight(50);
        button->setMaximumHeight(70);
        button->setFocusPolicy(Qt::NoFocus);
        button->setFlat(true);
        button->setFont(QFont("Arial", 12));
        button->setCheckable(true);
        button->setVisible(false);
        button->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
        buttonLayout->addWidget(button);
        buttons.push_back(button);
        connect(button, SIGNAL(clicked()), this, SLOT(itemClicked()));
    }
}

void StaticScrollArea::SetSelectedIndex(int index)
{
    selectedIndex = index;
    emit SelectionChanged(selectedIndex);
    updateButtons();
}

void StaticScrollArea::SetOptions(vector<string> &opts)
{
    options = opts;
    scrollbar->setRange(0, options.size()-buttons.size());

    updateButtons();
}

void StaticScrollArea::scrolled(int index)
{
    currentOffset = index;
    updateButtons();
}

void StaticScrollArea::updateButtons()
{
    for(int i=0; i<buttons.size(); i++)
    {
        int index = currentOffset + i;
        QPushButton* button = buttons[i];
        button->setVisible(index < options.size());
        button->setChecked(index == selectedIndex);
        if (index < options.size())
            button->setText(options[index].c_str());
    }
}

void StaticScrollArea::itemClicked()
{
    QPushButton* button = (QPushButton*)sender();
    int index = std::find(buttons.begin(), buttons.end(), button) - buttons.begin();
    SetSelectedIndex(index + currentOffset);
}


QScrollBar* StaticScrollArea::GetScrollbar()
{
    return scrollbar;
}
