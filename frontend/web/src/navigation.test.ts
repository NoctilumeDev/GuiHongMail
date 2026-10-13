import { describe, expect, it } from 'vitest'
import { navigation } from './navigation'

describe('frozen mailbox navigation', () => {
  it('contains exactly the seven approved entries in order', () => {
    expect(navigation.map(item => item.label)).toEqual(['写信', '收件箱', '已发邮件', '草稿箱', '归档', '垃圾邮件', '已删除'])
    expect(navigation).toHaveLength(7)
  })
})
