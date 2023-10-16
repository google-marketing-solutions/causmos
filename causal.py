import causalimpact
import re

def getCiObject(df, pre_period, post_period):
    impact = causalimpact.fit_causalimpact(df, pre_period, post_period)   
    return impact  

def getCiSummary(impact):
    summary = causalimpact.summary(impact, output_format='summary')
    summary = re.sub('  +', '|', summary)
    summary_arr = [r.split('|') for r in [r for r in summary.split('\n')]]
    return summary_arr
    
def getCiChart(impact):
    return causalimpact.plot(impact, static_plot=False,chart_width=800).to_html()

def getCiReport(impact):
    report = causalimpact.summary(impact, output_format='report')
    report = report.replace('\n\n', '<br><br>')
    return report