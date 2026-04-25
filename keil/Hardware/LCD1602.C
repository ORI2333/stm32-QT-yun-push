 #include  "LCD1602.h"
 
 /******************************************************************************
  * 函数名称:void GPIO_Configuration()                           *
  * 函数功能:LCD1602引脚初始化                                                        *
  * 输入参数:无                                                   *
  * 返回值  :无                                                                *
  * 其他说明:                                                                    *
  ******************************************************************************/
 /*******************根据自己的硬件引脚做修改*****************************************/
 void GPIO_Configuration(void)
 {
     GPIO_InitTypeDef GPIO_InitStructure;
     RCC_APB2PeriphClockCmd( RCC_APB2Periph_GPIOA | RCC_APB2Periph_GPIOB, ENABLE );
     GPIO_InitStructure.GPIO_Pin = GPIO_Pin_11 | GPIO_Pin_12 | GPIO_Pin_13;
     GPIO_InitStructure.GPIO_Speed   = GPIO_Speed_50MHz;//选择工作频率
     GPIO_InitStructure.GPIO_Mode    = GPIO_Mode_Out_PP;//设置工作模式
     GPIO_Init( GPIOA, &GPIO_InitStructure );
 
     GPIO_InitStructure.GPIO_Pin = GPIO_Pin_0 | GPIO_Pin_1 | GPIO_Pin_2 | GPIO_Pin_3 | GPIO_Pin_4 | GPIO_Pin_5 | GPIO_Pin_6 | GPIO_Pin_7;
     GPIO_InitStructure.GPIO_Mode    = GPIO_Mode_Out_PP;//设置工作模式
     GPIO_InitStructure.GPIO_Speed   = GPIO_Speed_50MHz;//选择工作频率
     GPIO_Init( GPIOB, &GPIO_InitStructure );
 }
 /******************************************************************************
  * 函数名称:void LCD1602_Init()                         *
  * 函数功能:LCD1602初始化                                                      *
  * 输入参数:无                                                   *
  * 返回值  :无                                                                *
  * 其他说明:                                                                    *
  ******************************************************************************/
 void LCD1602_Init(void)
 {
     GPIO_Configuration();           //初始化引脚
 
     LCD1602_Write_Cmd( 0x38 );      //显示模式设置
     Delay_ms( 5 );
     LCD1602_Write_Cmd( 0x0c );      //显示开及光标设置
     Delay_ms( 5 );
     LCD1602_Write_Cmd( 0x06 );      //显示光标移动位置
     Delay_ms( 5 );
     LCD1602_Write_Cmd( 0x01 );      //显示清屏
     Delay_ms( 5 );  
 }
 /******************************************************************************
  * 函数名称:void LCD1602_Write_Cmd(u8 cmd)                          *
  * 函数功能:写命令函数                                                           *
  * 输入参数:    cmd 命令                                                      *
  * 返回值  :无                                                                *
  * 其他说明:                                                                    *
  ******************************************************************************/
 void LCD1602_Write_Cmd( u8 cmd )
 {
     LCD_RS_Clr();
     LCD_RW_Clr();
     LCD_EN_Set();
 
     GPIO_Write( GPIOB, (GPIO_ReadOutputData( GPIOB ) & 0xff00) | cmd );//对电平的读取
 
     DATAOUT( cmd );
     Delay_ms( 5 );
     LCD_EN_Clr();
 }
 
 /******************************************************************************
  * 函数名称:void LCD1602_Write_Dat(u8 date)                         *
  * 函数功能:写数据函数                                                           *
  * 输入参数:    date 数据                                                     *
  * 返回值  :无                                                                *
  * 其他说明:                                                                    *
  ******************************************************************************/
 void LCD1602_Write_Dat( u8 data )
 {
     LCD_RS_Set();
     LCD_RW_Clr();
     LCD_EN_Set();
 
     GPIO_Write( GPIOB, (GPIO_ReadOutputData( GPIOB ) & 0xff00) | data );//对电平的读取
 
     Delay_ms( 5 );
     LCD_EN_Clr();
 }
 
 /******************************************************************************
  * 函数名称:void LCD1602_ClearScreen()                          *
  * 函数功能:1602清屏函数                                                            *
  * 输入参数:无                                                       *
  * 返回值  :无                                                                *
  * 其他说明:                                                                    *
  ******************************************************************************/
 void LCD1602_ClearScreen(void)
 {
     LCD1602_Write_Cmd( 0x01 );
 }
 
 /******************************************************************************
  * 函数名称:void LCD1602_Set_Cursor(u8 x, u8 y)                         *
  * 函数功能:设置1602位置函数                                                    *
  * 输入参数:x 横坐标 y 纵坐标                                                     *
  * 返回值  :无                                                                *
  * 其他说明:                                                                    *
  ******************************************************************************/
 void LCD1602_Set_Cursor( u8 x, u8 y )
 {
     u8 addr;
 
     if ( y == 0 )
         addr = 0x00 + x;
     else
         addr = 0x40 + x;
     LCD1602_Write_Cmd( addr | 0x80 );
 } 
 /******************************************************************************
  * 函数名称:void LCD1602_Show_Str( u8 x, u8 y, u8 *str )                            *
  * 函数功能:指定位置显示字符串函数                                                   *
  * 输入参数:x 横坐标 y 纵坐标     *str 字符串                                  *
  * 返回值  :   无                                                             *
  * 其他说明:                                                                    *
  ******************************************************************************/
 void LCD1602_Show_Str( u8 x, u8 y, u8 *str )
 {
     LCD1602_Set_Cursor( x, y );
     while ( *str != '\0' )
     {
         LCD1602_Write_Dat( *str++ );
     }
 }
 
 
 
