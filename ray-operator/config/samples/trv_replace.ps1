# Get the source directory from the argument
$src = $args[0]

# Define a dictionary of text pairs to replace
$replaceDict = @{
#    "serviceType: ClusterIP" = "serviceType: NodePort"
    "image: rayproject/ray:" = "image: quay.apps.mgmt1.ocp.trafikverket.local/registry-1.docker.io/rayproject/ray:"
    "image: busybox:" = "image: proget.trafikverket.local/docker/library/busybox:"
    # You can add more text pairs here
}

# Get all the files under the source directory
$files = Get-ChildItem -Path $src -File -Recurse -Include *.yaml

# Write the number of files to the console
Write-Output "Number of files to examine: $($files.Count)"

# Initialize a variable to store the number of modified files
$modified = 0

# Loop through each file and replace the text
foreach ($file in $files) {
    # Read the file content as a single string
    $content = Get-Content -Path $file.FullName -Raw

    # Store the original content for comparison
    $original = $content

    # Loop through each text pair in the dictionary
    foreach ($pair in $replaceDict.GetEnumerator()) {
        # Replace the old text with the new text
        $content = $content -replace $pair.Key, $pair.Value
    }

    # Check if the content has changed
    if ($content -ne $original) {
        # Write the modified content back to the file without a new line
        Set-Content -Path $file.FullName -Value $content -NoNewline

        # Write the output to the console
        Write-Output "Modified file: $($file.FullName)"

        # Increment the number of modified files
        $modified++
    }
}

# Write the final output to the console
Write-Output "Total number of modified files: $modified"