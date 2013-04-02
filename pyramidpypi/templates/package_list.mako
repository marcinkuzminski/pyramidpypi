<!DOCTYPE html>
<html>
<head>
    <title>${title}</title>
</head>
<body>
    % for link, package in sorted(zip(links, packages)):
        <a href="${link}">${package}</a><br/>
    % endfor
</body>
</html>
