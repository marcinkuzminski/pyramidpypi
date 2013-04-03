<!DOCTYPE html>
<html>
<head>
    <title>${title}</title>
</head>
<body>
    % for package, link in sorted(packages_links):
        <a href="${link}">${package}</a><br/>
    % endfor
</body>
</html>
