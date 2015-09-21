#ifndef QWTGRAPHFRAME_H
#define QWTGRAPHFRAME_H

#include <QFrame>
#include <QMutex>
#include <qwt_plot.h>
#include <qwt_scale_draw.h>
#include <qwt_plot_multi_barchart.h>
#include <qwt_column_symbol.h>

using namespace std;

class QwtPlotMultiBarChart;
class LabeledMultiBarChart;
class LabelScaleDraw;

class QwtGraphFrame : public QwtPlot
{
    Q_OBJECT
public:
    explicit QwtGraphFrame(QWidget *parent = 0);

    void ShowBarChart(map<string, double> &values);
    void ShowBarChart(vector<string> &labels, vector<double> &values);
    //void ShowStackedBarChart(vector<string> &labels, vector<double> &values);

public Q_SLOTS:
    void setMode( int );
    void setOrientation( int );

private:
    LabeledMultiBarChart * barChart;
    QMutex dataLock;
    LabelScaleDraw* xAxis;
    
};

class LabeledMultiBarChart : public QwtPlotMultiBarChart
{
public:
    LabeledMultiBarChart();

    virtual void drawBar(QPainter *painter, int sampleIndex, int barIndex, const QwtColumnRect &rect) const
    {
        QwtPlotMultiBarChart::drawBar(painter, sampleIndex, barIndex, rect);
        double val = sample(sampleIndex).set[barIndex];
        QRectF rectF = rect.toRect();
        rectF.setTop(rectF.top() - 15);
        painter->drawText(rectF, Qt::AlignHCenter, QString("%1").arg(val));
    }

};

class LabelScaleDraw : public QwtScaleDraw
{
public:
    LabelScaleDraw() { }

    virtual QwtText label(double v) const
    {
        int index = (int)v;
        if (index >= 0 && index < Labels.size())
            return QString(Labels[index].c_str());
        return QString();
    }

    vector<string> Labels;
};

#endif // QWTGRAPHFRAME_H
