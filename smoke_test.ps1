$ErrorActionPreference = 'Stop'
$ts = [int](Get-Date -UFormat %s)
$email = "smoke$ts@optio.news"
$pw = 'Smoke123!'
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$pass = 0; $fail = 0

function Check($name, $condition, $detail='') {
    if ($condition) { Write-Host "  PASS  $name $detail" -ForegroundColor Green; $script:pass++ }
    else            { Write-Host "  FAIL  $name $detail" -ForegroundColor Red;   $script:fail++ }
}

Write-Host "`nOptio News Smoke Test — $email`n" -ForegroundColor Cyan

# 1 Register
$r = Invoke-WebRequest 'https://optio.news/register' -Method POST -Body @{email=$email;password=$pw;confirm_password=$pw} -WebSession $s -UseBasicParsing -MaximumRedirection 5
Check "Register (200)"          ($r.StatusCode -eq 200)
Check "Register → main page"   ($r.Content -match 'articlesGrid')

# 2 API articles — an empty list is OK only while the server reports it is
# still warming its cache (first crawl after a deploy)
$arts = Invoke-RestMethod 'https://optio.news/api/articles' -WebSession $s
Check "GET /api/articles (200)"   ($null -ne $arts.articles)
Check "Articles present (or warming)" ($arts.articles.Count -gt 0 -or $arts.warming -eq $true) "count=$($arts.articles.Count) warming=$($arts.warming)"
Check "feed_count > 0"            ($arts.feed_count -gt 0)

# 3 API refresh
$ref = Invoke-RestMethod 'https://optio.news/api/refresh' -WebSession $s
Check "GET /api/refresh"          ($null -ne $ref.articles -or $ref.status -eq 'ok' -or $ref.Count -ge 0)

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
$bmBody = [System.Text.Encoding]::UTF8.GetBytes('{"url":"https://example.com","title":"Smoke Test","tags":["test"]}')
$bma = Invoke-RestMethod 'https://optio.news/api/bookmarks' -Method POST -ContentType 'application/json' -Body $bmBody -WebSession $s
Check "POST /api/bookmarks"       ($bma.id -gt 0) "id=$($bma.id)"
Check "Bookmark title correct"    ($bma.title -eq 'Smoke Test')

# 8 Bookmark list
$bml = Invoke-RestMethod 'https://optio.news/api/bookmarks' -WebSession $s
Check "GET /api/bookmarks"        ($bml.bookmarks.Count -gt 0) "count=$($bml.bookmarks.Count)"

# 9 Bookmark edit
$editBody = [System.Text.Encoding]::UTF8.GetBytes('{"title":"Updated"}')
$bme = Invoke-RestMethod "https://optio.news/api/bookmarks/$($bma.id)" -Method PUT -ContentType 'application/json' -Body $editBody -WebSession $s
Check "PUT /api/bookmarks/:id"    ($bme.title -eq 'Updated')

# 10 Bookmark delete
$bmd = Invoke-RestMethod "https://optio.news/api/bookmarks/$($bma.id)" -Method DELETE -WebSession $s
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
$ua = Invoke-WebRequest 'https://optio.news/' -WebSession $s2 -UseBasicParsing -MaximumRedirection 5
Check "Unauthed / → login"        ($ua.Content -match 'login')

# 15 Login with existing user
$s3 = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$li = Invoke-WebRequest 'https://optio.news/login' -Method POST -Body @{email=$email;password=$pw} -WebSession $s3 -UseBasicParsing -MaximumRedirection 5
Check "POST /login"               ($li.Content -match 'articlesGrid')

# 16 Delete the throwaway account so smoke runs leave no residue
$del = Invoke-RestMethod 'https://optio.news/api/account' -Method DELETE -WebSession $s3
Check "DELETE /api/account"       ($del.success -eq $true)

$color = if ($fail -eq 0) {'Green'} else {'Yellow'}
Write-Host "`n--- Results: $pass passed, $fail failed ---`n" -ForegroundColor $color
