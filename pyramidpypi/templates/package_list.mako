<!DOCTYPE html>
<html>
<head>
    <title>${title}</title>
</head>
<body>
    % for package, link in packages_links:
        <a href="${link}">${package}</a><br/>
    % endfor
</body>
</html>
