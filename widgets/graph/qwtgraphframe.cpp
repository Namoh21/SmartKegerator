#include <widgets/graph/qwtgraphframe.h>
#include <qwt_plot_renderer.h>
#include <qwt_plot_canvas.h>
#include <qwt_plot_multi_barchart.h>
#include <qwt_column_symbol.h>
#include <qwt_plot_layout.h>
#include <qwt_legend.h>
#include <qwt_scale_draw.h>


LabeledMultiBarChart::LabeledMultiBarChart() : QwtPlotMultiBarChart("") { }

QwtGraphFrame::QwtGraphFrame( QWidget *parent ):
    QwtPlot( parent )
{
    //setAutoFillBackground( true );

    setFrameShape(QFrame::NoFrame);

    //setPalette( Qt::yellow );
    canvas()->setAutoFillBackground(false);
    plotLayout()->setCanvasMargin(0);
    canvas()->setPalette( QColor(120,120,120) );

    xAxis = new LabelScaleDraw();
    xAxis->setLabelRotation(-50);
    xAxis->setLabelAlignment(Qt::AlignLeft | Qt::AlignVCenter);

    barChart = new LabeledMultiBarChart();
    barChart->setLayoutPolicy( QwtPlotMultiBarChart::AutoAdjustSamples );
    barChart->setSpacing( 20 );
    barChart->setMargin( 3 );

    barChart->attach( this );

    //insertLegend(new QwtLegend(), QwtPlot::BottomLegend);


    // Create bar
    QwtColumnSymbol *symbol = new QwtColumnSymbol( QwtColumnSymbol::Box );
    symbol->setLineWidth( 2 );
    symbol->setFrameStyle( QwtColumnSymbol::NoFrame );
    symbol->setPalette( QPalette( "SteelBlue" ) );

    barChart->setSymbol( 0, symbol );

    setOrientation( 0 );
    //setMode(1);

    setAutoReplot( true );
}

void QwtGraphFrame::setMode( int mode )
{
    if ( mode == 0 )
    {
        barChart->setStyle( QwtPlotMultiBarChart::Grouped );
    }
    else
    {
        barChart->setStyle( QwtPlotMultiBarChart::Stacked );
    }
}

void QwtGraphFrame::setOrientation( int orientation )
{
    QwtPlot::Axis axis1, axis2;

    if ( orientation == 0 )
    {
        axis1 = QwtPlot::xBottom;
        axis2 = QwtPlot::yLeft;

        barChart->setOrientation( Qt::Vertical );
    }
    else
    {
        axis1 = QwtPlot::yLeft;
        axis2 = QwtPlot::xBottom;

        barChart->setOrientation( Qt::Horizontal );
    }

    setAxisScaleDraw( axis1, xAxis);

    setAxisAutoScale( axis2 );

    QwtScaleDraw *scaleDraw1 = axisScaleDraw( axis1 );
    scaleDraw1->enableComponent( QwtScaleDraw::Backbone, false );
    scaleDraw1->enableComponent( QwtScaleDraw::Ticks, false );

    QwtScaleDraw *scaleDraw2 = axisScaleDraw( axis2 );
    scaleDraw2->enableComponent( QwtScaleDraw::Backbone, true );
    scaleDraw2->enableComponent( QwtScaleDraw::Ticks, true );

    plotLayout()->setAlignCanvasToScale( axis1, true );
    plotLayout()->setAlignCanvasToScale( axis2, false );

    plotLayout()->setCanvasMargin( 0 );
    updateCanvasMargins();
}

void QwtGraphFrame::ShowBarChart(map<string, double> &vals)
{
    vector<string> labels;
    vector<double> values;

    map<string, double>::iterator iter;
    for (iter = vals.begin(); iter != vals.end(); iter++)
    {
        labels.push_back(iter->first);
        values.push_back(iter->second);
    }

    ShowBarChart(labels, values);
}

void QwtGraphFrame::ShowBarChart(vector<string> &labels, vector<double> &values)
{
    xAxis->Labels = labels;
    QVector< QVector<double> > series;
    for ( int i = 0; i < values.size(); i++ )
    {
        QVector<double> s;
        s += values[i];
        series += s;
    }
    barChart->setSamples( series );


    int startRotatingAfter = 4;
    if (barChart->dataSize() <= startRotatingAfter)
        xAxis->setLabelAlignment(Qt::AlignCenter);
    else
        xAxis->setLabelAlignment(Qt::AlignLeft | Qt::AlignVCenter);
    double angle = min(0, max(-50, ((int)(barChart->dataSize())-startRotatingAfter) * -15));
    xAxis->setLabelRotation(angle);

    setAxisScale( QwtPlot::xBottom, 0, barChart->dataSize() - 1, 1.0 );
    updateCanvasMargins();

    replot();
}
