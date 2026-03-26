
# Optio News

**Your daily personalized news digest with a modern web interface, smart filtering, and customizable RSS feed management.**

<img width="2494" height="1290" alt="firefox_pWW9LI1QHY" src="https://github.com/user-attachments/assets/0816dbe9-4990-4b69-9da7-dfe627b936ac" />

---

## Features

### Content Coverage
- **9 News Categories**: Technology, Finance, General News, Sports, Science, Business, Entertainment, Music, and Health
- **70+ Premium RSS Sources**: Curated feeds from top publications across all categories
- **27+ Additional Feeds Available**: Easily add more sources to customize your news experience
- **Real-time Updates**: Articles cached for 30 minutes with manual refresh option

### Trending Topics
- **Real-time Trend Analysis**: Identifies trending topics from the last 24 hours of articles
- **Smart Keyword Extraction**: Uses frequency analysis with 2-3 word phrase detection
- **Filtered Results**: Removes 200+ common stopwords and generic terms for meaningful trends
- **Live Sidebar**: Always-visible trending topics panel with related articles
- **Sticky Navigation**: Sidebar scrolls independently for easy browsing

### Feed Management
- **View Active Feeds**: See all your current RSS sources in one organized dashboard
- **Hide/Unhide Feeds**: Temporarily disable feeds you don't want without permanently removing them
- **Add New Feeds**: Browse and activate additional RSS sources from our curated collection
- **Search & Filter**: Quickly find specific feeds by name, URL, or category
- **Persistent Settings**: Your feed preferences are saved and restored on restart

### Modern Web Interface
- **Beautiful Responsive Design**: Works seamlessly on desktop, tablet, and mobile
- **Dark/Light Theme**: Toggle between themes with persistent preference
- **Smooth Animations**: Professional transitions and micro-interactions
- **Category-coded Design**: Blue color scheme for easy visual scanning

### Advanced Filtering
- **Category Filtering**: Click any category to focus on specific topics
- **Live Search**: Real-time search across titles and summaries
- **Smart Results**: Instant filtering without page reloads
- **Keyboard Shortcuts**: `Ctrl+K` to focus search, `Esc` to clear

### Email Integration
- **Daily Digest**: Automated email delivery at 9:00 AM
- **HTML Formatting**: Beautiful, responsive email templates
- **Grouped by Category**: Organized presentation of articles
- **Customizable Schedule**: Easy to adjust timing in code

---

## Quick Start

### 1. Prerequisites

- **Python 3.8+** installed
- **Git** (optional, for cloning)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/leifheaney5/optio-news.git
cd optio-news

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Create a `.env` file in the project root:

```env
SENDER_EMAIL=your_gmail_address@gmail.com
APP_PASSWORD=your_gmail_app_password
RECEIVER_EMAIL=recipient_email_address@gmail.com
```

> **Gmail Users**: Use an [App Password](https://myaccount.google.com/apppasswords) if you have 2FA enabled (NOT your regular password).

### 4. Run the Application

```bash
python main.py
```

The web interface will be available at: **http://localhost:5000**

---

## Usage

### Web Interface

1. Open your browser to `http://localhost:5000`
2. Browse articles from all categories or filter by specific topics
3. Use the search bar to find articles by keyword
4. Click category badges to filter content
5. Toggle between light/dark themes with the moon/sun icon
6. Click "Read More" on any article to view the full story

### Feed Management

1. Click the gear icon in the top right corner
2. **Active Feeds Tab**: View and manage your current RSS sources
   - See which feeds are active or hidden
   - Hide feeds you don't want by clicking "Hide Feed"
   - Restore hidden feeds by clicking "Restore Feed"
   - Search through your active feeds
3. **Add New Feeds Tab**: Browse and add new RSS sources
   - Filter by category or search for specific feeds
   - Click "Add Feed" to activate new sources
   - See which feeds are already added

### Email Delivery

- Emails are automatically sent daily at 9:00 AM
- Email contains all articles formatted in a clean, readable layout
- Articles are grouped by category for easy navigation

---

## Mobile Experience

Optio News is fully responsive and optimized for mobile devices:

- Touch-friendly interface
- Swipeable category filters
- Optimized card layouts
- Fast loading times
- Readable typography

---

## Customization

### Adding/Removing RSS Feeds

Edit the `rss_feeds` dictionary in `main.py`:

```python
rss_feeds = {
    "Your Category": [
        "https://example.com/feed.xml",
        "https://another-source.com/rss"
    ]
}
```

Or use the web interface to add feeds from the available collection.

### Changing Email Schedule

Modify the schedule line in `main.py`:

```python
# Change from 9:00 AM to your preferred time
schedule.every().day.at("06:00").do(job)  # 6 AM
```

### Adjusting Cache Duration

Update the cache timeout in the `fetch_articles` function:

```python
if age < timedelta(minutes=60):  # Change from 30 to 60 minutes
```

### Adding New Available Feeds

Edit the `available_feeds` dictionary in `main.py` to add more options to the feed browser:

```python
available_feeds = {
    "Category": [
        {"url": "https://newfeed.com/rss", "name": "New Feed Name"},
    ]
}
```

---

## Technology Stack

- **Backend**: Python 3.8+, Flask
- **Frontend**: Vanilla JavaScript, CSS3, HTML5
- **RSS Parsing**: feedparser
- **Email**: smtplib with HTML templates
- **Scheduling**: schedule library
- **Storage**: File-based persistence for settings
- **Icons**: Font Awesome 6
- **Fonts**: Inter (Google Fonts)

---

## File Structure

```
Optio News/
├── main.py                 # Flask application and RSS feed logic
├── requirements.txt        # Python dependencies
├── hidden_feeds.txt        # User's hidden feeds (auto-generated)
├── .env                    # Environment variables (create this)
├── templates/
│   ├── index.html         # Main news page
│   └── feeds.html         # Feed management page
└── static/
    ├── css/
    │   ├── style.css      # Main styles
    │   └── feeds.css      # Feed management styles
    └── js/
        ├── app.js         # Main application logic
        └── feeds.js       # Feed management logic
```

---

## Automation

### Windows (Task Scheduler)

1. Open Task Scheduler
2. Create a new task to run `python main.py` at startup
3. Set it to run whether user is logged in or not

### Linux/Mac (cron)

```bash
# Add to crontab (crontab -e)
@reboot cd /path/to/Optio News && python3 main.py
```

### Docker (Coming Soon)

We're working on Docker support for even easier deployment!

---

## Troubleshooting

### Port Already in Use

```bash
# Change the port in main.py
app.run(debug=True, host='0.0.0.0', port=5001)
```

### Email Not Sending

- Verify your `.env` file is in the correct location
- Confirm you're using an App Password (not your regular password)
- Check that your Gmail account has "Less secure app access" enabled if needed

### Articles Not Loading

- Check your internet connection
- Some RSS feeds may be temporarily unavailable
- Try the refresh button to force a new fetch

### Feed Management Not Saving

- Ensure the application has write permissions in its directory
- Check that `hidden_feeds.txt` can be created/modified
- Review console logs for any error messages

---

## License

This project is open source and available under the MIT License.

---

## Contributing

Contributions are welcome! Feel free to:

- Report bugs
- Suggest new features
- Submit pull requests
- Add new RSS feed sources

---

## Support
- Developer: Leif Heaney  
  Contact: leif@leifheaney.com
  Portfolio: [www.leifheaney.com](https://leifheaney.com/)
  GitHub: https://github.com/leifheaney5

---

**Stay up to date with your daily news using Optio News!**


