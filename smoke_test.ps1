$ErrorActionPreference = 'Stop'
$ts = [int](Get-Date -UFormat %s)
$email = "smoke$ts@optio.news"
$pw = 'Smoke123!Pass'
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$pass = 0; $fail = 0

function Get-CsrfToken($url, $session) {
    $page = Invoke-WebRequest $url -WebSession $session -UseBasicParsing
    $match = [regex]::Match($page.Content, 'name="csrf-token"[^>]+content="([^"]+)"')
    if (-not $match.Success) { $match = [regex]::Match($page.Content, 'name="csrf_token"[^>]+value="([^"]+)"') }
    if (-not $match.Success) { throw "No CSRF token on $url" }
    return $match.Groups[1].Value
}

function Invoke-JsonCsrf($url, $method, $body, $session) {
    $token = Get-CsrfToken 'https://optio.news/reader' $session
    $headers = @{ 'X-CSRFToken' = $token }
    Invoke-RestMethod $url -Method $method -ContentType 'application/json' -Body $body -Headers $headers -WebSession $session
}

function Check($name, $condition, $detail='') {
    if ($condition) { Write-Host "  PASS  $name $detail" -ForegroundColor Green; $script:pass++ }
    else            { Write-Host "  FAIL  $name $detail" -ForegroundColor Red;   $script:fail++ }
}

Write-Host "`nOptio News Smoke Test - $email`n" -ForegroundColor Cyan

# 1 Register
$registerToken = Get-CsrfToken 'https://optio.news/register' $s
$r = Invoke-WebRequest 'https://optio.news/register' -Method POST -Body @{email=$email;password=$pw;confirm_password=$pw;csrf_token=$registerToken} -WebSession $s -UseBasicParsing -MaximumRedirection 5
Check "Register (200)"          ($r.StatusCode -eq 200)
Check "Register -> main page"   ($r.Content -match 'articlesGrid')
Check "Daily digest opt-in"      ($r.Content -match 'id="settingsDigest"' -and $r.Content -match 'Send me a daily news roundup')

# 2 API articles — content is populated asynchronously by the worker.
$arts = Invoke-RestMethod 'https://optio.news/api/articles' -WebSession $s
Check "GET /api/articles (200)"   ($null -ne $arts.articles)
Check "Database-backed article response" ($arts.storage -eq 'database') "count=$($arts.articles.Count)"
Check "feed_count > 0"            ($arts.feed_count -gt 0)

# 3 API refresh
$ref = Invoke-RestMethod 'https://optio.news/api/refresh' -WebSession $s
Check "GET /api/refresh"          ($ref.success -eq $true -and $ref.status -eq 'worker_refresh_scheduled')

# 4 API trending
$trend = Invoke-RestMethod 'https://optio.news/api/trending' -WebSession $s
Check "GET /api/trending"         ($null -ne $trend.trending)

# 5 Suggestions
$sugg = Invoke-RestMethod 'https://optio.news/api/feeds/suggestions?category=Technology' -WebSession $s
Check "GET /api/feeds/suggestions" ($null -ne $sugg.suggestions)

# 6 Preview
$prev = Invoke-RestMethod 'https://optio.news/api/preview?url=https://example.com' -WebSession $s
Check "GET /api/preview"          ($null -ne $prev)

# 7 Bookmark add
$bmBody = '{"url":"https://example.com","title":"Smoke Test","tags":["test"]}'
$bma = Invoke-JsonCsrf 'https://optio.news/api/bookmarks' 'POST' $bmBody $s
Check "POST /api/bookmarks"       ($bma.id -gt 0) "id=$($bma.id)"
Check "Bookmark title correct"    ($bma.title -eq 'Smoke Test')

# 8 Bookmark list
$bml = Invoke-RestMethod 'https://optio.news/api/bookmarks' -WebSession $s
Check "GET /api/bookmarks"        ($bml.bookmarks.Count -gt 0) "count=$($bml.bookmarks.Count)"

# 9 Bookmark edit
$editBody = '{"title":"Updated"}'
$bme = Invoke-JsonCsrf "https://optio.news/api/bookmarks/$($bma.id)" 'PUT' $editBody $s
Check "PUT /api/bookmarks/:id"    ($bme.title -eq 'Updated')

# 10 Bookmark delete
$bmd = Invoke-JsonCsrf "https://optio.news/api/bookmarks/$($bma.id)" 'DELETE' '' $s
Check "DELETE /api/bookmarks/:id" ($bmd.success -eq $true)

# 11 Feeds page
$fp = Invoke-WebRequest 'https://optio.news/feeds' -WebSession $s -UseBasicParsing
Check "GET /feeds (200)"          ($fp.StatusCode -eq 200)

# 12 Bookmarks page
$bp = Invoke-WebRequest 'https://optio.news/bookmarks' -WebSession $s -UseBasicParsing
Check "GET /bookmarks (200)"      ($bp.StatusCode -eq 200)
Check "/bookmarks has bmGrid"     ($bp.Content -match 'bmGrid')

# 13 Logout
$lo = Invoke-WebRequest 'https://optio.news/logout' -WebSession $s -UseBasicParsing -MaximumRedirection 5
Check "GET /logout redirects"     ($lo.StatusCode -eq 200)
Check "After logout → login page" ($lo.Content -match 'login')

# 14 Unauthed access → redirect to login
$s2 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$ua = Invoke-WebRequest 'https://optio.news/reader' -WebSession $s2 -UseBasicParsing -MaximumRedirection 5
Check "Unauthed /reader -> login"   ($ua.Content -match 'login')

# 15 Login with existing user
$s3 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginToken = Get-CsrfToken 'https://optio.news/login' $s3
$li = Invoke-WebRequest 'https://optio.news/login' -Method POST -Body @{email=$email;password=$pw;csrf_token=$loginToken} -WebSession $s3 -UseBasicParsing -MaximumRedirection 5
Check "POST /login"               ($li.Content -match 'articlesGrid')

# 16 Delete the throwaway account so smoke runs leave no residue
$del = Invoke-JsonCsrf 'https://optio.news/api/account' 'DELETE' '' $s3
Check "DELETE /api/account"       ($del.success -eq $true)

$color = if ($fail -eq 0) {'Green'} else {'Yellow'}
Write-Host "`n--- Results: $pass passed, $fail failed ---`n" -ForegroundColor $color
