name: 每日消息简报

on:
  schedule:
    - cron: '30 0 * * *'   # 北京时间 8:30
    - cron: '10 6 * * *'   # 北京时间 14:10
  workflow_dispatch:

jobs:
  run-briefing:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v6

    - name: Set up Python
      uses: actions/setup-python@v6
      with:
        python-version: '3.10'

    - name: Install system deps & fonts
      run: |
        sudo apt-get update
        sudo apt-get install -y fonts-wqy-zenhei

    - name: Install Python deps
      run: pip install requests matplotlib

    - name: Download morning cache
      uses: actions/download-artifact@v4
      with:
        name: morning-news
        path: morning_data
      continue-on-error: true

    - name: Run briefing
      env:
        EMAIL_USER: ${{ secrets.EMAIL_USER }}
        EMAIL_PASS: ${{ secrets.EMAIL_PASS }}
        EMAIL_TO: ${{ secrets.EMAIL_TO }}
        DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
        MORNING_DATA_PATH: morning_data/morning_news.json
      run: python main.py

    - name: Upload morning cache
      if: success()
      uses: actions/upload-artifact@v4
      with:
        name: morning-news
        path: morning_news.json
        retention-days: 1
