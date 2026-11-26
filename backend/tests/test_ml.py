import pandas as pd
from app.ml.engine import detect_anomalies, forecast_series

def test_anomaly_detector_flags_outlier():
    df=pd.DataFrame({"sales":[10,11,9,10,12,11,10,9,11,10,500],"units":[1,2,1,2,1,2,1,2,1,2,99]})
    result=detect_anomalies(df)
    assert result["available"] and result["count"]>=1

def test_forecast_requires_enough_data():
    df=pd.DataFrame({"date":pd.date_range("2024-01-01",periods=5,freq="MS"),"sales":[1,2,3,4,5]})
    assert forecast_series(df,"date","sales")["available"] is False
