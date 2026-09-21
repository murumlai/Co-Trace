const relativePath = (file) => file.webkitRelativePath || ''

export function selectDroppedFiles(dropped) {
  const files = Array.from(dropped)
  const hasFolder = files.some((file) => relativePath(file).includes('/'))

  if (hasFolder) return { files, replace: true, error: '' }

  const zips = files.filter((file) => file.name.toLowerCase().endsWith('.zip'))
  if (zips.length) {
    const ignored = files.length - 1
    return {
      files: zips.slice(0, 1),
      replace: true,
      error: ignored
        ? `Only one .zip can be loaded at a time. ${ignored} other file${ignored === 1 ? '' : 's'} ignored.`
        : '',
    }
  }

  const textFiles = files.filter((file) => file.name.toLowerCase().endsWith('.txt'))
  const skipped = files.length - textFiles.length
  return {
    files: textFiles,
    replace: false,
    error: skipped
      ? `${skipped} file${skipped === 1 ? '' : 's'} skipped - only .txt files can be added individually.`
      : '',
  }
}