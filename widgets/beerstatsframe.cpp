#include "widgets/beerstatsframe.h"
#include <QFont>
#include <QTimer>
#include <QCoreApplication>
#include <QTime>
#include <QMouseEvent>
#include <data/keg.h>
#include <data/user.h>
#include <data/pour.h>
#include <data/constants.h>

BeerStatsFrame::BeerStatsFrame(QWidget *parent) :
    QFrame(parent)
{
    setFrameShape(QFrame::NoFrame);

    panels = 4;
    padding = 10;
    extraPadding = 2;
    xOffset = 0;
    currentPanel = 0;

    dragging = false;
    AutoScrollEnabled = true;

    dowNames.push_back(QString("sun"));
    dowNames.push_back(QString("mon"));
    dowNames.push_back(QString("tue"));
    dowNames.push_back(QString("wed"));
    dowNames.push_back(QString("thur"));
    dowNames.push_back(QString("fri"));
    dowNames.push_back(QString("sat"));

    headerHeight = 20;
    footerHeight = 10;

    CurrentKeg = NULL;

    tileBrush = QBrush(QColor(150,150,150,150));
    barBrush = QBrush(QColor(0, 183, 205, 150));
    textPen = QPen(QColor(200,200,200,150));

    idleTimer = new QTimer(this);
    idleTimer->setSingleShot(true);
    connect(idleTimer, SIGNAL(timeout()), this, SLOT(nextPane()));
    resetIdle();
}

void BeerStatsFrame::SetKeg(Keg *keg)
{
    CurrentKeg = keg;
    update();
}

int dragThreshold = 25;
double velocity = 0;

void BeerStatsFrame::mousePressEvent(QMouseEvent *ev)
{
    resetIdle();
    if (ev->button() != Qt::LeftButton)
        return;
    dragStartX = ev->pos().x() - xOffset;
    dragging = false;
    velocity = 0;
    ev->accept();
}

void BeerStatsFrame::mouseMoveEvent(QMouseEvent *ev)
{
    resetIdle();
    ev->accept();
    int delta = dragStartX - ev->pos().x();
    if (abs(delta) > dragThreshold)
        dragging = true;
    if (dragging == false)
        return;
    velocity = (4.0*velocity + ((ev->pos().x() - dragStartX) - xOffset))/5.0; // this doesnt actually work since move events only happen on moves
    xOffset = ev->pos().x() - dragStartX;
    update();
}

void BeerStatsFrame::mouseReleaseEvent(QMouseEvent *ev)
{
    resetIdle();
    ev->accept();
    if (dragging == false)
    {
        nextPane();
    }
    else
    {
        velocity = (9.0*velocity + ((ev->pos().x() - dragStartX) - xOffset))/10.0; // this doesnt actually work since move events only happen on moves
        xOffset = ev->pos().x() - dragStartX;
        int dest = xOffset + 10*velocity - 0.5*frameWidth;
        currentPanel = max(0, min(panels-1, -dest/frameWidth));
    }

    dragging = false;
    update();
}

void BeerStatsFrame::nextPane()
{
    if (AutoScrollEnabled)
    {
        currentPanel = (currentPanel + 1) % panels;
        update();
    }
    resetIdle();
}

void BeerStatsFrame::resetIdle()
{
    int high = 60 * 1000;
    int low = 10 * 1000;
    int idleTimeout = qrand() % ((high + 1) - low) + low;
    idleTimer->start(idleTimeout);
}

void BeerStatsFrame::paintEvent(QPaintEvent *event)
{
    QPainter painter(this);

    painter.setRenderHint(QPainter::Antialiasing);

    frameWidth = width();
    frameHeight = height();

    if (CurrentKeg == NULL)
    {
        drawNone(painter, QString("empty"));
        return;
    }

    drawFooter(painter);

    int panel = -xOffset / frameWidth;
    int offset = (int)xOffset % frameWidth;

    drawContent(painter, panel, offset);
    if (offset != 0)
        drawContent(painter, panel + 1, offset + frameWidth);

    int panelX = currentPanel * -frameWidth;

    if (dragging == false && xOffset != panelX)
    {
        float speed = 20;
        xOffset = ((speed-1)*xOffset + panelX)/speed;
        if ((int)(xOffset-0.5) == panelX)
            xOffset = panelX;

        QTime dieTime = QTime::currentTime().addMSecs(10);
        while(QTime::currentTime() < dieTime)
            QCoreApplication::processEvents(QEventLoop::AllEvents, 10);

        update();
    }
}

void BeerStatsFrame::drawContent(QPainter &painter, int panel, int offset)
{
    vector< QPair<QString, double> > pairs;

    switch(panel)
    {
        case 0: // recent pours
        {
            drawHeader(painter, QString("recent pours"), offset);

            int maxTiles = 4;
            vector< QPair<QString, QString> > stringPairs;
            vector<Pour*> pours = Pour::PoursByKegId[CurrentKeg->Id];
            int len = min(maxTiles, (int)pours.size());
            for (int i=0; i<len; i++)
            {
                Pour* pour = pours[pours.size() - i - 1];
                User* user = User::UsersById[pour->UserId];
                stringPairs.push_back(QPair<QString, QString>(QString(user->Name.c_str()),QString::number(i+1)));
            }

            if (stringPairs.size() == 0)
                drawNone(painter, QString("none"), offset);
            else
                drawTiles(painter, stringPairs, offset);
        }
        break;
        case 1: // today's pours
        {
            drawHeader(painter, QString("today's pours"), offset);

            map<User*, int> userPours;
            vector<Pour*> pours = Pour::PoursByKegId[CurrentKeg->Id];
            double now = time(NULL);
            for (int i=0; i<pours.size(); i++)
            {
                Pour* pour = pours[i];
                if (now - pour->Time >= 0.5 * Constants::Day)
                    continue;
                User* user = User::UsersById[pour->UserId];
                userPours[user]++;
            }

            vector< QPair<QString, QString> > stringPairs;

            map<User*, int>::iterator iter;
            for (iter = userPours.begin(); iter != userPours.end(); iter++)
                stringPairs.push_back(QPair<QString, QString>(QString(iter->first->Name.c_str()),QString::number(iter->second)));


            if (stringPairs.size() == 0)
                drawNone(painter, QString("none"), offset);
            else
                drawTiles(painter, stringPairs, offset);
        }
        break;
        case 2: //pours by day
        {
            drawHeader(painter, QString("pours by day"), offset);

            // DOW of week pours
            vector<int> dowPours = Pour::GetPoursByDow(CurrentKeg);
            //int dowPours[] = {22, 5, 12, 13, 11, 24, 20};
            int maxDowPours = 0;
            for (int i=0; i<7; i++)
                maxDowPours = max(dowPours[i], maxDowPours);

            for (int i=0; i<7; i++)
                pairs.push_back(QPair<QString, double>(dowNames[i],dowPours[i]/(double)maxDowPours));

            if (maxDowPours == 0)
                drawNone(painter, QString("none"), offset);
            else
                drawBars(painter, pairs, offset);
        }
        break;
        case 3: // pours by user
        {
            drawHeader(painter, QString("pours by user"), offset);

            if (CurrentKeg == NULL)
            {
                drawNone(painter, QString("none"), offset);
                return;
            }

            map<User*, int> userPours = Pour::GetPoursByUser(CurrentKeg);
            int maxPours = 0;
            map<User*, int>::iterator iter;
            for (iter = userPours.begin(); iter != userPours.end(); iter++)
                maxPours = max(maxPours, iter->second);

            for (iter = userPours.begin(); iter != userPours.end(); iter++)
                pairs.push_back(QPair<QString, double>(QString(iter->first->Name.c_str()),iter->second/(double)maxPours));

            if (maxPours == 0)
                drawNone(painter, QString("none"), offset);
            else
                drawBars(painter, pairs, offset);
        }
        break;
    }
}

void BeerStatsFrame::drawNone(QPainter &painter, QString str, int offset)
{
    painter.setPen(QPen(QColor(200,200,200,100)));
    painter.setFont(QFont("Sans Serif", 22));
    painter.drawText(QRect(offset + padding, padding, frameWidth - 2 * padding, frameHeight - 2 * padding), Qt::AlignCenter, str);
}

void BeerStatsFrame::drawBars(QPainter &painter, vector< QPair<QString, double> > vals, int offset)
{
    double maxBarWidth = 50;
    int w = frameWidth - 2 * padding;
    double barSpacing = min(maxBarWidth, w/(double)vals.size());
    int barWidth = barSpacing - 2 * extraPadding;
    double x = 0.5 * (frameWidth - vals.size() * barSpacing) + extraPadding + offset;
    int barHeight = frameHeight - footerHeight - headerHeight - 2 * padding;

    painter.setPen(QPen(Qt::transparent));
    painter.setBrush(barBrush);
    painter.setFont(QFont("Sans Serif", 7));

    for (int i=0; i<vals.size(); i++)
    {
        QPair<QString, double> pair = vals[i];
        int h = barHeight * pair.second;
        painter.drawRect(x + i * barSpacing, headerHeight + barHeight + extraPadding, barWidth, -h);
    }

    painter.setPen(textPen);
    for (int i=0; i<vals.size(); i++)
    {
        QPair<QString, double> pair = vals[i];
        painter.drawText(QRect(x + i * barSpacing, headerHeight + barHeight + extraPadding, barWidth, headerHeight), Qt::AlignCenter, pair.first);
    }
}

void BeerStatsFrame::drawTiles(QPainter &painter, vector< QPair<QString, QString> > vals, int offset)
{
    int tileHeight = frameHeight - footerHeight - headerHeight - padding;
    int w = frameWidth - 2 * padding;
    double tileSpacing = min((double)tileHeight + extraPadding, w/(double)vals.size());
    int tileWidth = tileSpacing - 2 * extraPadding;
    double x = padding + extraPadding + offset;

    painter.setPen(QPen(Qt::transparent));
    painter.setBrush(tileBrush);

    for (int i=0; i<vals.size(); i++)
        painter.drawRect(x + i * tileSpacing, headerHeight + extraPadding, tileWidth, tileHeight);

    int nameHeight = 14;

    painter.setPen(textPen);
    for (int i=0; i<vals.size(); i++)
    {
        QPair<QString, QString> pair = vals[i];
        painter.setFont(QFont("Sans Serif", 32));
        painter.drawText(QRect(x + i * tileSpacing, headerHeight + extraPadding, tileWidth, tileHeight - nameHeight), Qt::AlignCenter, pair.second);
        painter.setFont(QFont("Sans Serif", 8));
        painter.drawText(QRect(x + i * tileSpacing, headerHeight + tileHeight - nameHeight, tileWidth, nameHeight), Qt::AlignCenter, pair.first);
    }
}

void BeerStatsFrame::drawHeader(QPainter &painter, QString text, int offset)
{
    painter.setPen(textPen);
    painter.setFont(QFont("Sans Serif", 10));
    painter.drawText(QRect(offset, 0, frameWidth, headerHeight), Qt::AlignCenter, text);
}

void BeerStatsFrame::drawFooter(QPainter &painter)
{
    painter.setPen(QPen(Qt::transparent));

    int radius = 3;
    int spacing = 9;

    int x = 0.5 * frameWidth - (0.5 * panels) * spacing;
    int y = frameHeight - 0.5 * footerHeight - extraPadding;

    for (int i=0; i<panels; i++)
    {
        if (i == currentPanel)
            painter.setBrush(QBrush(QColor(200,200,200,200)));
        else
           painter.setBrush(QBrush(QColor(200,200,200,100)));
        painter.drawEllipse(QPoint(x + i*spacing, y), radius, radius);
    }
}
